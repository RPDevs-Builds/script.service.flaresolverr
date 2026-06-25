import atexit
import logging
import os
import platform
import signal
from subprocess import PIPE
from subprocess import Popen
import sys


CREATE_NEW_PROCESS_GROUP = 0x00000200
DETACHED_PROCESS = 0x00000008

REGISTERED = []


def _popen_detached(executable, *args):
    """
    Start a detached subprocess directly via Popen.
    Used as the primary method on Android and as fallback on other platforms
    where multiprocessing is unavailable or broken.
    """
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    p = Popen([executable, *args], stdin=PIPE, stdout=PIPE, stderr=PIPE, **kwargs)
    REGISTERED.append(p.pid)
    return p.pid


def start_detached(executable, *args):
    """
    Starts a fully independent subprocess (with no parent).

    On platforms with full multiprocessing support (desktop Linux, macOS, Windows),
    this spawns a grandchild process via multiprocessing.Process so the child is
    fully detached from the Python process tree.

    On Android and other restricted platforms where multiprocessing semaphores
    are unavailable, falls back to a direct Popen with start_new_session=True.

    :param executable: executable
    :param args: arguments to the executable
    :return: pid of the launched process
    """
    try:
        # Lazy import — only attempted at call time, NOT at module load.
        # This prevents the ImportError on Android where multiprocessing's
        # synchronize module fails due to missing sem_open.
        import multiprocessing

        # create pipe
        reader, writer = multiprocessing.Pipe(False)

        # do not keep reference
        process = multiprocessing.Process(
            target=_start_detached_mp,
            args=(executable, *args),
            kwargs={"writer": writer},
            daemon=True,
        )
        process.start()
        process.join()
        # receive pid from pipe
        pid = reader.recv()
        REGISTERED.append(pid)
        # close pipes
        writer.close()
        reader.close()
        process.close()

        return pid
    except (ImportError, OSError, AttributeError) as e:
        logging.getLogger(__name__).warning(
            "undetected_chromedriver: multiprocessing unavailable (%s), using direct Popen", e
        )
        return _popen_detached(executable, *args)


def _start_detached_mp(executable, *args, writer=None):
    """
    Target function for multiprocessing.Process — runs the actual Popen
    inside a child process, sends the PID back via pipe, then exits.
    This makes the launched process a grandchild, fully detached.

    Only called when multiprocessing is available (never on Android).
    """
    import multiprocessing  # safe here — we're already in a mp.Process

    # configure launch
    kwargs = {}
    if platform.system() == "Windows":
        kwargs.update(creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
    elif sys.version_info < (3, 2):
        # assume posix
        kwargs.update(preexec_fn=os.setsid)
    else:  # Python 3.2+ and Unix
        kwargs.update(start_new_session=True)

    # run
    p = Popen([executable, *args], stdin=PIPE, stdout=PIPE, stderr=PIPE, **kwargs)

    # send pid to pipe
    writer.send(p.pid)
    sys.exit()


def _cleanup():
    for pid in REGISTERED:
        try:
            logging.getLogger(__name__).debug("cleaning up pid %d " % pid)
            os.kill(pid, signal.SIGTERM)
        except:  # noqa
            pass


atexit.register(_cleanup)
