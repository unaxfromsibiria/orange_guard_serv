import base64
import io
import os
import typing
import uuid

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from PIL.Image import Image
from PIL.Image import open as img_open

from .helpers import env_var_line
from .helpers import env_var_time

DEVICE = env_var_line("WEBCAM_DEVICE") or "video0"
RESOLUTION = env_var_line("WEBCAM_RESOLUTION") or "640x480"

NETWORK_CHECK_TIMEOUT = env_var_time("NETWORK_CHECK_TIMEOUT") or 600
fig, ax = plt.subplots()

ax.fmt_xdata = mdates.DateFormatter("%Y-%m-%d")
ax.grid(True)


def get_png_photo(png_factor: int = 9) -> typing.Optional[Image]:
    """Get image from web camera.
    apt-get install fswebcam
    """
    img_path = f"/tmp/{uuid.uuid4().hex}.png"
    os.system(
        f"fswebcam -r {RESOLUTION} --no-banner "
        f"--device /dev/{DEVICE} --png {png_factor} {img_path}"
    )
    if os.path.exists(img_path):
        image = img_open(img_path)
        os.remove(img_path)
    else:
        image = None

    return image


def png_img_to_buffer(img: Image) -> io.BytesIO:
    """Image data to base64
    """
    buffer = io.BytesIO()
    img.save(buffer, "png")
    buffer.seek(0)
    return buffer


def png_img_to_base64(img: Image) -> str:
    """Image data to base64
    """
    with io.BytesIO() as buffer:
        img.save(buffer, "png")
        buffer.seek(0)
        result = base64.b64encode(buffer.getvalue()).decode()

    return result


def table_to_image(
    data: pd.DataFrame, titile: str = ""
) -> io.BytesIO:
    """Create image with rate table.
    """
    dia = data.plot()
    if titile:
        ax.set_title(titile)

    buffer = io.BytesIO()
    img = dia.get_figure()
    img.savefig(buffer)
    buffer.seek(0)
    return buffer
