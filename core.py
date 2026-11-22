"""AutoCompilateur - coeur : decompresse un ZIP, detecte Gradle/Maven, prepare Java et compile en .jar.
Aucune dependance externe (bibliotheque standard Python uniquement)."""
import os
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

IS_WIN = os.name == "nt"
BASE = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")) / "AutoCompilateur"
TOOLS = BASE / "outils"
WORK = BASE / "travail"
SUPPORTED_JAVA = (8, 11, 17, 21, 25)
GRADLE_DEFAULT, GRADLE_JAVA25, MAVEN_VERSION = "8.10.2", "9.1.0", "3.9.9"
UA = {"User-Agent": "AutoCompilateur/1.0"}
MARKERS = ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "pom.xml")


class BuildError(Exception):
    pass


def q(path):
    return '"%s"' % path


# ------------------------------------------------------------------ telechargement / extraction
def download(url, dest, log):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    log("Telechargement : " + url)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done, nxt = 0, 10 << 20
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if done >= nxt:
                    log("  ... %d Mo%s" % (done >> 20, (" / %d Mo" % (total >> 20)) if total else ""))
                    nxt += 10 << 20
    except Exception as e:
        raise BuildError("Telechargement impossible (%s) : %s" % (url, e))
    tmp.replace(dest)


def safe_extract(zip_path, dest):
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as z:
        for m in z.infolist():
            target = (dest / m.filename).resolve()
            if target != dest and dest not in target.parents:
                raise BuildError("ZIP refuse (chemin suspect) : " + m.filename)
        z.extractall(dest)


# ------------------------------------------------------------------ detection du projet
def find_root(work):
    best = None
    work = Path(work)
    for dirpath, dirs, files in os.walk(work):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "build", "target")]
        depth = len(Path(dirpath).relative_to(work).parts)
        if depth > 4:
            dirs[:] = []
            continue
        if any(m in files for m in MARKERS):
            score = (depth, 0 if any(f.startswith("settings.gradle") for f in files) else 1)
            if best is None or score < best[0]:
                best = (score, Path(dirpath))
    return best[1] if best else None


def detect_kind(root):
    files = {p.name for p in Path(root).iterdir()}
    if any(f.startswith(("build.gradle", "settings.gradle")) for f in files):
        return "gradle"
    if "pom.xml" in files:
        return "maven"
    return None


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")[:300000]
    except OSError:
        return ""


def round_up(n):
    for s in SUPPORTED_JAVA:
        if n <= s:
            return s
    return SUPPORTED_JAVA[-1]


JAVA_PATTERNS = (
    r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)",
    r"options\.release(?:\.set\(|\s*=\s*)\s*(\d+)",
    r"sourceCompatibility\s*=\s*['\"]?(?:1\.)?(\d+)",
    r"targetCompatibility\s*=\s*['\"]?(?:1\.)?(\d+)",
    r"<maven\.compiler\.release>\s*(\d+)",
    r"<maven\.compiler\.source>\s*(?:1\.)?(\d+)",
    r"<maven\.compiler\.target>\s*(?:1\.)?(\d+)",
    r"<release>\s*(\d+)\s*</release>",
    r"<java\.version>\s*(?:1\.)?(\d+)",
)


def detect_java(root, log):
    root = Path(root)
    text = "".join(_read(root / n) for n in ("build.gradle", "build.gradle.kts", "pom.xml", "gradle.properties"))
    found = []
    for pat in JAVA_PATTERNS:
        found += [int(x) for x in re.findall(pat, text)]
    for a, b in re.findall(r"JavaVersion\.VERSION_(\d+)(?:_(\d+))?", text):
        found.append(int(b) if a == "1" and b else int(a))
    if found:
        major = round_up(max(found))
        log("Java requis detecte dans les fichiers du projet : %d" % major)
        return major
    m = re.search(r"minecraft_version\s*=\s*1\.(\d+)(?:\.(\d+))?", _read(root / "gradle.properties"))
    if m:
        minor, patch = int(m.group(1)), int(m.group(2) or 0)
        major = 21 if (minor >= 21 or (minor == 20 and patch >= 5)) else 17 if minor >= 17 else 8
        log("Java deduit de la version de Minecraft (1.%d) : %d" % (minor, major))
        return major
    log("Version de Java non detectee : Java 21 par defaut (modifiable dans le menu).")
    return 21


# ------------------------------------------------------------------ Java / Gradle / Maven
def java_major_of(home):
    txt = _read(Path(home) / "release")
    m = re.search(r'JAVA_VERSION="([^"]+)"', txt)
    if not m:
        return None
    parts = m.group(1).split(".")
    try:
        return int(parts[1]) if parts[0] == "1" and len(parts) > 1 else int(re.match(r"\d+", parts[0]).group())
    except (AttributeError, ValueError):
        return None


def installed_jdks():
    homes = []
    if os.environ.get("JAVA_HOME"):
        homes.append(Path(os.environ["JAVA_HOME"]))
    for base in (r"C:\Program Files\Eclipse Adoptium", r"C:\Program Files\Java", r"C:\Program Files\Microsoft",
                 r"C:\Program Files\Zulu", r"C:\Program Files\Amazon Corretto"):
        b = Path(base)
        if b.is_dir():
            homes += [p for p in b.iterdir() if p.is_dir()]
    exe = "javac.exe" if IS_WIN else "javac"
    return [h for h in homes if (h / "bin" / exe).exists()]


def ensure_jdk(major, log):
    for h in installed_jdks():
        if java_major_of(h) == major:
            log("Java %d trouve : %s" % (major, h))
            return h
    dest = TOOLS / ("jdk-%d" % major)
    exe = "javac.exe" if IS_WIN else "javac"
    if (dest / "bin" / exe).exists():
        return dest
    if not IS_WIN:
        raise BuildError("Telechargement automatique de Java : Windows uniquement. Installe Java %d." % major)
    log("Java %d absent : telechargement (premiere fois seulement, ~200 Mo)..." % major)
    url = "https://api.adoptium.net/v3/binary/latest/%d/ga/windows/x64/jdk/hotspot/normal/eclipse" % major
    archive = TOOLS / ("jdk-%d.zip" % major)
    download(url, archive, log)
    tmp = TOOLS / ("_tmp_jdk_%d" % major)
    shutil.rmtree(tmp, ignore_errors=True)
    safe_extract(archive, tmp)
    inner = next((p for p in tmp.iterdir() if (p / "bin" / exe).exists()), None)
    if inner is None:
        raise BuildError("Archive Java inattendue.")
    shutil.rmtree(dest, ignore_errors=True)
    shutil.move(str(inner), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)
    return dest


def wrapper_version(root):
    txt = _read(Path(root) / "gradle" / "wrapper" / "gradle-wrapper.properties")
    m = re.search(r"gradle-([0-9][0-9.]*(?:-[a-z]+-[0-9]+)?)-(?:bin|all)\.zip", txt)
    return m.group(1) if m else None


def ensure_gradle(version, log):
    dest = TOOLS / ("gradle-" + version)
    exe = dest / "bin" / ("gradle.bat" if IS_WIN else "gradle")
    if exe.exists():
        return exe
    log("Gradle %s absent : telechargement..." % version)
    archive = TOOLS / ("gradle-%s-bin.zip" % version)
    download("https://services.gradle.org/distributions/gradle-%s-bin.zip" % version, archive, log)
    safe_extract(archive, TOOLS)
    archive.unlink(missing_ok=True)
    if not exe.exists():
        raise BuildError("Gradle %s introuvable apres extraction." % version)
    return exe


def ensure_maven(log):
    dest = TOOLS / ("apache-maven-" + MAVEN_VERSION)
    exe = dest / "bin" / ("mvn.cmd" if IS_WIN else "mvn")
    if exe.exists():
        return exe
    log("Maven %s absent : telechargement..." % MAVEN_VERSION)
    archive = TOOLS / ("maven-%s.zip" % MAVEN_VERSION)
    download("https://archive.apache.org/dist/maven/maven-3/%s/binaries/apache-maven-%s-bin.zip" % (MAVEN_VERSION, MAVEN_VERSION), archive, log)
    safe_extract(archive, TOOLS)
    archive.unlink(missing_ok=True)
    if not exe.exists():
        raise BuildError("Maven introuvable apres extraction.")
    return exe


def run(cmdline, cwd, jdk, log):
    env = dict(os.environ)
    env["JAVA_HOME"] = str(jdk)
    env["PATH"] = str(Path(jdk) / "bin") + os.pathsep + env.get("PATH", "")
    log("> " + cmdline)
    p = subprocess.Popen(cmdline, cwd=str(cwd), env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", creationflags=(0x08000000 if IS_WIN else 0))
    lines = []
    for line in p.stdout:
        line = line.rstrip()
        lines.append(line)
        log(line)
    return p.wait(), lines


def build_gradle(root, jdk, major, log):
    wrapper = Path(root) / ("gradlew.bat" if IS_WIN else "gradlew")
    if wrapper.exists():
        log("Utilisation du wrapper Gradle du projet.")
        exe = q(wrapper)
    else:
        ver = wrapper_version(root) or (GRADLE_JAVA25 if major >= 25 else GRADLE_DEFAULT)
        exe = q(ensure_gradle(ver, log))
    base = exe + " build --no-daemon --console=plain"
    rc, lines = run(base + " -x test", root, jdk, log)
    if rc != 0 and any("Task 'test' not found" in l for l in lines):
        rc, lines = run(base, root, jdk, log)
    return rc, lines


def build_maven(root, jdk, log):
    return run(q(ensure_maven(log)) + " -B -DskipTests package", root, jdk, log)


# ------------------------------------------------------------------ resultat
def collect_jars(root):
    root = Path(root)
    skip = ("-sources.jar", "-javadoc.jar", "-dev.jar", "-dev-shadow.jar", "-all-dev.jar")
    found = []
    for pat in ("**/build/libs/*.jar", "**/target/*.jar"):
        for p in root.glob(pat):
            n = p.name.lower()
            if n.endswith(skip) or n.startswith("original-"):
                continue
            found.append(p)
    names = {p.name for p in found}
    return [p for p in found if not any(p.name[:-4] + "-all.jar" == n or p.name[:-4] + "-shaded.jar" == n for n in names)]


def explain(lines):
    text = "\n".join(lines[-200:])
    hints = []
    if re.search(r"Unsupported class file major version|Could not determine java version|requires Java|Unsupported Java", text):
        hints.append("Mauvaise version de Java : essaie une autre valeur dans le menu Java.")
    if re.search(r"Could not resolve|Could not GET|Could not transfer|UnknownHost|Connection (?:timed out|refused)", text):
        hints.append("Telechargement de dependances impossible : verifie ta connexion internet ou reessaie plus tard.")
    if re.search(r"error:|cannot find symbol|COMPILATION ERROR|Compilation failed", text):
        hints.append("Le code du projet contient des erreurs de compilation : copie le journal et demande de l'aide.")
    return "La compilation a echoue. " + (" ".join(hints) if hints else "Regarde le journal pour la cause.")


def compile_zip(zip_path, java_choice, log):
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise BuildError("Fichier introuvable : %s" % zip_path)
    work = WORK / re.sub(r"[^\w.-]+", "_", zip_path.stem)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    log("Decompression de %s ..." % zip_path.name)
    try:
        safe_extract(zip_path, work)
    except zipfile.BadZipFile:
        raise BuildError("Ce fichier n'est pas un ZIP valide.")
    root = find_root(work)
    if root is None:
        raise BuildError("Aucun projet trouve (pas de build.gradle, build.gradle.kts ni pom.xml dans le ZIP).")
    kind = detect_kind(root)
    log("Projet %s detecte : %s" % (kind, root.name))
    major = int(java_choice) if str(java_choice).isdigit() else detect_java(root, log)
    jdk = ensure_jdk(major, log)
    rc, lines = build_gradle(root, jdk, major, log) if kind == "gradle" else build_maven(root, jdk, log)
    if rc != 0:
        raise BuildError(explain(lines))
    jars = collect_jars(root)
    if not jars:
        raise BuildError("La compilation a reussi mais aucun .jar n'a ete trouve (build/libs ou target).")
    out = zip_path.parent / (zip_path.stem + "-jar")
    out.mkdir(exist_ok=True)
    copied = []
    for j in jars:
        shutil.copy2(j, out / j.name)
        copied.append(out / j.name)
    log("Termine : %d fichier(s) .jar dans %s" % (len(copied), out))
    return out, copied
