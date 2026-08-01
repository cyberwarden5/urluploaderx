import os
import math
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

import cv2
from PIL import Image, ImageDraw

logger = logging.getLogger("URLUploaderBot.SS")

_executor = ThreadPoolExecutor(max_workers=4)


def _format_timestamp(seconds: float) -> str:
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _create_collage(pil_images: list[tuple[Image.Image, str]], output_path: str) -> None:
    num = len(pil_images)
    if num == 0:
        return

    cols = min(3, num)
    rows = math.ceil(num / cols)
    thumb_w, thumb_h = 480, 270
    header_h = 60
    grid_w = cols * thumb_w
    grid_h = rows * thumb_h + header_h

    collage = Image.new("RGB", (grid_w, grid_h), color=(20, 20, 25))
    draw = ImageDraw.Draw(collage)

    # Header
    draw.rectangle([(0, 0), (grid_w, header_h)], fill=(30, 34, 42))
    draw.text((20, 18), "VIDEO SCREENSHOT COLLAGE", fill=(0, 210, 255))

    for idx, (img, ts_str) in enumerate(pil_images):
        row = idx // cols
        col = idx % cols
        x = col * thumb_w
        y = row * thumb_h + header_h

        resized = img.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        collage.paste(resized, (x, y))

        draw.rectangle(
            [(x, y), (x + thumb_w - 1, y + thumb_h - 1)],
            outline=(50, 50, 60),
            width=2,
        )
        draw.rectangle([(x + 10, y + 10), (x + 110, y + 34)], fill=(0, 0, 0))
        draw.text((x + 15, y + 14), ts_str, fill=(255, 255, 255))

    collage.save(output_path, quality=95)
    collage.close()
    logger.info("Collage saved: %s (%dx%d)", output_path, grid_w, grid_h)


def _extract_sync(video_path: str, output_dir: str, count: int = 10, progress_cb=None):
    os.makedirs(output_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps and fps > 0 else 0

        if total_frames <= 0 or duration <= 0:
            raise ValueError("Invalid or zero-length video.")

        step = duration / (count + 1)
        timestamps = [step * (i + 1) for i in range(count)]

        extracted: list[dict] = []
        pil_images: list[tuple[Image.Image, str]] = []

        for i, ts in enumerate(timestamps):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
            ret, frame = cap.read()
            if not ret:
                logger.warning("Frame %d at %.2fs unreadable, skipping", i, ts)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            ts_str = _format_timestamp(ts)

            frame_path = os.path.join(output_dir, f"screenshot_{i + 1:02d}.jpg")
            img.save(frame_path, quality=95)

            extracted.append({"path": frame_path, "timestamp": ts_str, "seconds": ts})
            pil_images.append((img, ts_str))

            if progress_cb:
                try:
                    progress_cb(i + 1, count)
                except Exception:
                    pass

        if not extracted:
            raise ValueError("No frames could be extracted.")

        collage_path = os.path.join(output_dir, "collage.jpg")
        _create_collage(pil_images, collage_path)

        for img, _ in pil_images:
            img.close()

        return extracted, collage_path

    finally:
        cap.release()


async def extract_video_screenshots(
    video_path: str, output_dir: str, count: int = 10, progress_cb=None
):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _extract_sync, video_path, output_dir, count, progress_cb)
