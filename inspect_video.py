"""Temporary local video frame extractor for diagnosing the owner's recording."""

import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

source = Path(sys.argv[1])
output = Path(sys.argv[2])
output.mkdir(exist_ok=True)
app = QCoreApplication([])
sink = QVideoSink()
player = QMediaPlayer()
player.setVideoOutput(sink)
seen = set()


def on_frame(frame):
    position = player.position()
    bucket = position // 250
    if bucket not in seen and frame.isValid():
        seen.add(bucket)
        frame.toImage().save(str(output / f"{position:05d}.png"))


sink.videoFrameChanged.connect(on_frame)
player.mediaStatusChanged.connect(
    lambda status: app.quit() if status == QMediaPlayer.MediaStatus.EndOfMedia else None
)
QTimer.singleShot(30000, app.quit)
player.setSource(QUrl.fromLocalFile(str(source)))
player.play()
app.exec()
print(f"saved={len(seen)} duration_ms={player.duration()}")
