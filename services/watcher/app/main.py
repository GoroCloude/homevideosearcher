"""Watcher service entry point.

Bootstraps logging, runs startup scan, selects observer (inotify vs polling),
then loops forever until interrupted.
"""
import asyncio
import logging

from . import config
from .watcher import VideoHandler, startup_scan

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info(
        "Watcher starting. watch_dir=%s polling=%s worker_url=%s",
        config.WATCH_DIR,
        config.WATCH_USE_POLLING,
        config.WORKER_URL,
    )

    # Startup scan: process files that arrived during container downtime (AUTO-04)
    await startup_scan(config.WATCH_DIR)

    # Observer class selection (AUTO-06)
    # WATCH_USE_POLLING=true → PollingObserver (for NFS/CIFS where inotify is absent)
    # Default → inotify Observer (efficient on local ext4; works through Docker bind mounts
    #           because inotify events propagate via the shared host kernel)
    if config.WATCH_USE_POLLING:
        from watchdog.observers.polling import PollingObserver
        ObserverClass = PollingObserver
        logger.info("Using PollingObserver (WATCH_USE_POLLING=true)")
    else:
        from watchdog.observers import Observer
        ObserverClass = Observer
        logger.info("Using inotify Observer (default)")

    loop = asyncio.get_running_loop()
    handler = VideoHandler(loop=loop)
    observer = ObserverClass()
    observer.schedule(handler, config.WATCH_DIR, recursive=False)
    observer.start()
    logger.info("Watching %s", config.WATCH_DIR)

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join()
        logger.info("Observer stopped")


if __name__ == "__main__":
    asyncio.run(main())
