from pathlib import Path


def _inside(process_path, install_path):
    try:
        process = Path(process_path).resolve()
        install = Path(install_path).resolve()
        return process == install or install in process.parents
    except (OSError, ValueError):
        return False


def _compact(value):
    return ''.join(
        char.casefold()
        for char in str(value or '')
        if char.isalnum()
    )


def _vdf_value(content, key):
    for line in content.splitlines():
        parts = line.strip().split('"')
        if len(parts) >= 4 and parts[1].casefold() == key.casefold():
            return parts[3].replace('\\\\', '\\')
    return None


def _steam_game(process_path):
    if not process_path:
        return None

    parts = Path(process_path).parts

    for index, part in enumerate(parts):
        if part.casefold() != 'steamapps':
            continue

        if index + 2 >= len(parts):
            continue

        if parts[index + 1].casefold() != 'common':
            continue

        steamapps = Path(*parts[:index + 1])
        install_folder = parts[index + 2]
        install_path = steamapps / 'common' / install_folder

        if not _inside(process_path, install_path):
            continue

        game_name = install_folder.replace('_', ' ')

        try:
            for manifest in steamapps.glob('appmanifest_*.acf'):
                try:
                    content = manifest.read_text(
                        encoding='utf-8',
                        errors='ignore'
                    )
                    manifest_folder = _vdf_value(content, 'installdir')

                    if manifest_folder and manifest_folder.casefold() == install_folder.casefold():
                        game_name = _vdf_value(content, 'name') or game_name
                        break
                except OSError:
                    continue
        except OSError:
            pass

        return {
            'game_name': game_name,
            'source': 'Steam manifest'
        }

    return None
import json
import os


def _epic_game(process_path):
    if not process_path:
        return None

    manifest_dir = (
        Path(os.environ.get('PROGRAMDATA', r'C:\ProgramData'))
        / 'Epic'
        / 'EpicGamesLauncher'
        / 'Data'
        / 'Manifests'
    )

    if not manifest_dir.is_dir():
        return None

    try:
        for manifest in manifest_dir.glob('*.item'):
            try:
                data = json.loads(manifest.read_text(encoding='utf-8-sig'))
            except (OSError, json.JSONDecodeError):
                continue

            install_path = data.get('InstallLocation')
            if install_path and _inside(process_path, install_path):
                return {
                    'game_name': data.get('DisplayName') or data.get('AppName') or Path(install_path).name,
                    'source': 'Epic manifest'
                }
    except OSError:
        pass

    return None


def _xbox_game(process_path, window_title):
    if not process_path:
        return None

    parts = Path(process_path).parts

    for index, part in enumerate(parts):
        if part.casefold() != 'xboxgames' or index + 1 >= len(parts):
            continue

        folder = parts[index + 1]
        if folder.casefold() in {'content', 'data', 'games'}:
            continue

        return {
            'game_name': window_title.strip() if window_title else folder.replace('_', ' '),
            'source': 'Xbox installation'
        }

    return None


def _process_title_game(process_name, window_title):
    if not process_name or not window_title:
        return None

    stem = Path(process_name).stem.strip()
    title = window_title.strip()

    ignored = {
        'applicationframehost', 'backgroundtaskhost',
        'crashreportclient', 'easyanticheat',
        'epicgameslauncher', 'explorer', 'gamebar',
        'gameoverlayui', 'launcher', 'riotclientservices',
        'steam', 'steamwebhelper', 'unitycrashhandler',
        'unrealcefsubprocess', 'werfault', 'code'
    }

    if stem.casefold() in ignored:
        return None

    suffixes = (
        '-win64-shipping', '-win32-shipping',
        '_win64_shipping', '_win32_shipping',
        '-shipping', '_shipping', '-win64', '-win32'
    )

    clean_stem = stem.casefold()
    for suffix in suffixes:
        if clean_stem.endswith(suffix):
            clean_stem = clean_stem[:-len(suffix)]
            break

    if clean_stem in ignored:
        return None

    process_key = _compact(clean_stem)
    title_key = _compact(title)

    if len(process_key) < 4 or len(title_key) < 4:
        return None

    if (
        title_key == process_key
        or title_key.startswith(process_key)
        or process_key.startswith(title_key)
    ):
        return {
            'game_name': title,
            'source': 'Process and window title'
        }

    return None


def _folder_title_game(process_path, window_title):
    if not process_path or not window_title:
        return None

    ignored = {
        'binaries', 'bin', 'content', 'data', 'engine',
        'game', 'games', 'launcher', 'shipping',
        'win32', 'win64', 'x64', 'x86'
    }

    title_key = _compact(window_title)

    if len(title_key) < 4:
        return None

    current = Path(process_path).parent

    for _ in range(6):
        folder = current.name
        folder_key = _compact(folder)

        if (
            folder.casefold() not in ignored
            and len(folder_key) >= 4
            and (
                folder_key == title_key
                or title_key.startswith(folder_key)
                or folder_key.startswith(title_key)
            )
        ):
            return {
                'game_name': window_title.strip(),
                'source': 'Install folder and window title'
            }

        if current.parent == current:
            break

        current = current.parent

    return None


def detect_game_from_process(window_info):
    if not window_info:
        return None

    process_path = window_info.get('process_path')
    process_name = window_info.get('process_name')
    window_title = window_info.get('window_title') or ''

    for detector in (
        lambda: _steam_game(process_path),
        lambda: _epic_game(process_path),
        lambda: _xbox_game(process_path, window_title),
        lambda: _process_title_game(process_name, window_title),
        lambda: _folder_title_game(process_path, window_title)
    ):
        result = detector()
        if result:
            return result

    return None