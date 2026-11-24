import shutil
import sqlite3
import subprocess
import unicodedata
from contextlib import contextmanager

from datetime import datetime
from pathlib import Path

from core.paths import REPLAY_DIR, SAVED_DIR, FFMPEG


UNKNOWN_GAME = "Sem jogo identificado"

MONTHS = (
    "Janeiro", "Fevereiro", "Março", "Abril",
    "Maio", "Junho", "Julho", "Agosto",
    "Setembro", "Outubro", "Novembro", "Dezembro",
)

WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def safe_folder_name(value):
    """Converte o nome do jogo em um nome de pasta seguro para Windows."""
    name = unicodedata.normalize(
        "NFKC",
        str(value or UNKNOWN_GAME)
    ).strip()

    invalid = '<>:"/\\|?*'

    name = "".join(
        "_" if char in invalid or ord(char) < 32 else char
        for char in name
    ).rstrip(" .")

    if not name:
        name = UNKNOWN_GAME

    if name.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"

    return name[:80]


class ReplayLibrary:

    def __init__(
        self,
        saved_dir=SAVED_DIR,
        database_path=None,
        thumbnail_dir=None,
    ):
        self.saved_dir = Path(saved_dir)

        self.thumbnail_dir = Path(
            thumbnail_dir
            if thumbnail_dir is not None
            else REPLAY_DIR / "thumbnails"
        )

        self.database_path = Path(
            database_path
            if database_path is not None
            else REPLAY_DIR / "database" / "replays.db"
        )

        self.saved_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=10
        )

        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")

            with connection:
                yield connection

        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")

            connection.execute("""
                CREATE TABLE IF NOT EXISTS replays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    game_name TEXT NOT NULL,
                    captured_at REAL NOT NULL,
                    captured_at_local TEXT NOT NULL,
                    duration_seconds REAL,
                    file_size_bytes INTEGER NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    fps REAL,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'capture',
                    created_at REAL NOT NULL
                )
            """)

            # Migration: add thumbnail path without resetting existing records.
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(replays)"
                ).fetchall()
            }

            if "thumbnail_path" not in columns:
                connection.execute(
                    "ALTER TABLE replays ADD COLUMN thumbnail_path TEXT"
                )

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_replays_captured_at
                ON replays(captured_at DESC)
            """)

            connection.execute("""
                CREATE INDEX IF NOT EXISTS idx_replays_game_name
                ON replays(game_name)
            """)

    def register_existing(
        self,
        filepath,
        game_name=UNKNOWN_GAME,
        source="legacy",
        captured_at=None,
    ):
        """Registra um MP4 existente sem mover ou modificar o arquivo."""
        filepath = Path(filepath)

        if not filepath.is_file():
            raise FileNotFoundError(
                f"Replay não encontrado: {filepath}"
            )

        if filepath.suffix.lower() != ".mp4":
            raise ValueError("O replay precisa ser um arquivo MP4.")

        metadata = filepath.stat()

        timestamp = (
            metadata.st_mtime
            if captured_at is None
            else (
                captured_at.timestamp()
                if isinstance(captured_at, datetime)
                else float(captured_at)
            )
        )

        captured_local = datetime.fromtimestamp(
            timestamp
        ).astimezone().isoformat(timespec="seconds")

        with self.connect() as connection:
            cursor = connection.execute("""
                INSERT OR IGNORE INTO replays (
                    file_path,
                    file_name,
                    game_name,
                    captured_at,
                    captured_at_local,
                    file_size_bytes,
                    source,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(filepath.resolve()),
                filepath.name,
                str(game_name or UNKNOWN_GAME),
                timestamp,
                captured_local,
                metadata.st_size,
                source,
                datetime.now().timestamp(),
            ))

            return cursor.rowcount > 0

    def import_legacy_replays(self):
        """Importa registros antigos da raiz de saved, sem mover os MP4."""
        imported = 0

        files = sorted(
            self.saved_dir.glob("replay_*.mp4"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )

        for filepath in files:
            try:
                if self.register_existing(
                    filepath,
                    game_name=UNKNOWN_GAME,
                    source="legacy",
                ):
                    imported += 1

            except (OSError, ValueError, sqlite3.Error) as error:
                print(
                    f"[REPLAY LIBRARY] Falha ao importar "
                    f"{filepath.name}: {error}"
                )

        return imported

    def _unique_destination(self, destination):
        if not destination.exists():
            return destination

        index = 1

        while True:
            candidate = destination.with_name(
                f"{destination.stem}_{index:02d}"
                f"{destination.suffix}"
            )

            if not candidate.exists():
                return candidate

            index += 1

    def organize_replay(
        self,
        filepath,
        game_name=UNKNOWN_GAME,
        captured_at=None,
    ):
        """Move um novo replay para jogo/ano/mês/dia e registra no catálogo."""
        filepath = Path(filepath)

        if not filepath.is_file():
            raise FileNotFoundError(
                f"Replay não encontrado: {filepath}"
            )

        if filepath.suffix.lower() != ".mp4":
            raise ValueError("O replay precisa ser um arquivo MP4.")

        timestamp = (
            filepath.stat().st_mtime
            if captured_at is None
            else (
                captured_at.timestamp()
                if isinstance(captured_at, datetime)
                else float(captured_at)
            )
        )

        captured_date = datetime.fromtimestamp(timestamp)

        game_folder = safe_folder_name(game_name)

        # Uma ?nica pasta por jogo; a data fica no nome do arquivo.
        destination_dir = self.saved_dir / game_folder
        destination_dir.mkdir(parents=True, exist_ok=True)

        filename = (
            f"replay_{captured_date.strftime('%Y-%m-%d_%H-%M-%S')}.mp4"
        )

        destination = self._unique_destination(
            destination_dir / filename
        )

        source_path = filepath.resolve()
        destination_path = destination.resolve()

        moved = False

        try:
            if source_path != destination_path:
                shutil.move(
                    str(filepath),
                    str(destination)
                )
                moved = True

            self.register_existing(
                destination,
                game_name=str(game_name or UNKNOWN_GAME),
                source="capture",
                captured_at=timestamp,
            )

            self.ensure_thumbnail(destination)

            print(
                f"[REPLAY LIBRARY] Organizado: "
                f"{destination}"
            )

            return destination

        except Exception:
            # Se o registro falhar, tenta devolver o vídeo ao caminho original.
            if moved and destination.exists() and not filepath.exists():
                try:
                    filepath.parent.mkdir(
                        parents=True,
                        exist_ok=True
                    )
                    shutil.move(
                        str(destination),
                        str(filepath)
                    )
                except OSError as rollback_error:
                    print(
                        "[REPLAY LIBRARY] Falha ao restaurar "
                        f"arquivo original: {rollback_error}"
                    )

            raise

    def delete_replay(self, filepath):
        """Exclui o MP4, sua miniatura e seu registro do catalogo."""
        filepath = Path(filepath).resolve()
        saved_root = self.saved_dir.resolve()

        try:
            filepath.relative_to(saved_root)
        except ValueError:
            raise ValueError(
                "O arquivo nao pertence a pasta de replays do L Desktop."
            )

        with self.connect() as connection:
            record = connection.execute(
                """
                SELECT id, file_path, thumbnail_path
                FROM replays
                WHERE file_path = ?
                """,
                (str(filepath),),
            ).fetchone()

        if record is None:
            raise FileNotFoundError(
                f"Replay nao encontrado no catalogo: {filepath}"
            )

        if filepath.exists():
            filepath.unlink()

        with self.connect() as connection:
            connection.execute(
                "DELETE FROM replays WHERE id = ?",
                (record["id"],),
            )

        thumbnail_value = record["thumbnail_path"]

        if thumbnail_value:
            thumbnail = Path(thumbnail_value).resolve()

            try:
                thumbnail.relative_to(self.thumbnail_dir.resolve())
                thumbnail.unlink(missing_ok=True)
            except ValueError:
                print(
                    "[REPLAY LIBRARY] Miniatura fora da pasta permitida; "
                    "arquivo preservado."
                )
            except OSError as error:
                print(
                    f"[REPLAY LIBRARY] Nao foi possivel remover "
                    f"a miniatura: {error}"
                )

        print(f"[REPLAY LIBRARY] Replay excluido: {filepath.name}")

        return filepath

    def set_favorite(self, filepath, favorite=None):
        """Define ou alterna o status de favorito de um replay."""
        filepath = str(Path(filepath).resolve())

        with self.connect() as connection:
            record = connection.execute(
                """
                SELECT id, is_favorite
                FROM replays
                WHERE file_path = ?
                """,
                (filepath,),
            ).fetchone()

            if record is None:
                raise FileNotFoundError(
                    f"Replay nao encontrado no catalogo: {filepath}"
                )

            new_value = (
                not bool(record["is_favorite"])
                if favorite is None
                else bool(favorite)
            )

            connection.execute(
                """
                UPDATE replays
                SET is_favorite = ?
                WHERE id = ?
                """,
                (int(new_value), record["id"]),
            )

        return new_value

    def ensure_thumbnail(self, filepath):
        """Gera ou recupera a miniatura persistente de um replay."""
        filepath = Path(filepath).resolve()

        if not filepath.is_file():
            return None

        with self.connect() as connection:
            record = connection.execute(
                """
                SELECT id, thumbnail_path
                FROM replays
                WHERE file_path = ?
                """,
                (str(filepath),),
            ).fetchone()

        if record is None:
            return None

        existing = record["thumbnail_path"]

        if existing:
            existing_path = Path(existing)

            try:
                if (
                    existing_path.is_file()
                    and existing_path.stat().st_mtime >= filepath.stat().st_mtime
                ):
                    return existing_path
            except OSError:
                pass

        if not FFMPEG.is_file():
            print(
                f"[REPLAY LIBRARY] FFmpeg n?o encontrado para miniatura: {FFMPEG}"
            )
            return None

        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)

        thumbnail = self.thumbnail_dir / f"{record['id']}.jpg"
        temporary = self.thumbnail_dir / f"{record['id']}.tmp.jpg"

        command = [
            str(FFMPEG),
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", "1.0",
            "-i", str(filepath),
            "-frames:v", "1",
            "-vf",
            "scale=480:270:force_original_aspect_ratio=decrease,"
            "pad=480:270:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "4",
            str(temporary),
        ]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
            )

            if result.returncode != 0 or not temporary.is_file():
                temporary.unlink(missing_ok=True)
                print(
                    f"[REPLAY LIBRARY] N?o foi poss?vel gerar miniatura "
                    f"de {filepath.name}: {result.stderr}"
                )
                return None

            if temporary.stat().st_size == 0:
                temporary.unlink(missing_ok=True)
                return None

            temporary.replace(thumbnail)

            with self.connect() as connection:
                connection.execute(
                    """
                    UPDATE replays
                    SET thumbnail_path = ?
                    WHERE id = ?
                    """,
                    (str(thumbnail), record["id"]),
                )

            print(
                f"[REPLAY LIBRARY] Miniatura criada: {thumbnail.name}"
            )

            return thumbnail

        except (OSError, subprocess.TimeoutExpired) as error:
            temporary.unlink(missing_ok=True)
            print(
                f"[REPLAY LIBRARY] Erro ao gerar miniatura: {error}"
            )
            return None

    def list_replays(self, game_name=None, limit=100):
        """Retorna os replays mais recentes registrados no catálogo."""
        limit = max(1, min(int(limit), 10000))

        query = """
            SELECT *
            FROM replays
        """

        parameters = []

        if game_name:
            query += " WHERE game_name = ?"
            parameters.append(game_name)

        query += """
            ORDER BY captured_at DESC, id DESC
            LIMIT ?
        """

        parameters.append(limit)

        with self.connect() as connection:
            rows = connection.execute(
                query,
                parameters
            ).fetchall()

        return [dict(row) for row in rows]

    def list_games(self):
        """Retorna os jogos cadastrados e a quantidade de replays."""
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT game_name, COUNT(*) AS replay_count
                FROM replays
                GROUP BY game_name
                ORDER BY game_name COLLATE NOCASE
            """).fetchall()

        return [dict(row) for row in rows]

    def get_summary(self):
        with self.connect() as connection:
            row = connection.execute("""
                SELECT
                    COUNT(*) AS replay_count,
                    COUNT(DISTINCT game_name) AS game_count,
                    COALESCE(SUM(file_size_bytes), 0) AS total_bytes
                FROM replays
            """).fetchone()

        return dict(row)
