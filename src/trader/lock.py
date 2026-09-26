"""Lock entre processos (Windows, msvcrt): ciclo do agendador e vigia de fills do daemon nunca rodam juntos."""
import msvcrt
from contextlib import contextmanager

from trader.config import DATA_DIR


@contextmanager
def exclusive(name: str = "cycle"):
    """Levanta BlockingIOError na hora se outro processo segura o lock."""
    DATA_DIR.mkdir(exist_ok=True)
    fh = open(DATA_DIR / f"{name}.lock", "a+")
    try:
        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise BlockingIOError(f"lock '{name}' ocupado") from None
        try:
            yield
        finally:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        fh.close()
