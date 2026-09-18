"""Tesseract word boxes via the tesserocr wheel (bundled libtesseract; no binary needed).

Boxes are half-open integer pixels in the page image, the same frame as `pages.gt_words`.
On this build (tesserocr 2.11.0 / libtesseract 5.5.1), `BoundingBox` already returns a
half-open box (x1, y1 are one past the last ink pixel), so no adjustment is applied.

One PyTessBaseAPI per thread: the API object is not thread-safe, but Recognize releases the
GIL so a thread pool parallelises across cores.
"""
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from tesserocr import PSM, RIL, PyTessBaseAPI

# sha256 of data/tessdata/eng.traineddata (tessdata_fast). Pinned by scripts/fetch_tessdata.sh and
# folded into READ_VERSION so a different language model is a deliberate code change.
TESSDATA_SHA = "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
DPI = 150   # pages are A4 at 150 dpi; the JPEGs carry no DPI tag and Tesseract otherwise guesses


@dataclass(frozen=True)
class TessWord:
    word: str
    conf: float
    x0: int
    y0: int
    x1: int
    y1: int


class Tesseract:
    def __init__(self, tessdata_dir: Path):
        self.tessdata_dir = Path(tessdata_dir)
        if not (self.tessdata_dir / "eng.traineddata").exists():
            raise FileNotFoundError(
                f"{self.tessdata_dir}/eng.traineddata missing: run scripts/fetch_tessdata.sh"
            )
        self._local = threading.local()

    def _api(self) -> PyTessBaseAPI:
        api = getattr(self._local, "api", None)
        if api is None:
            api = PyTessBaseAPI(path=str(self.tessdata_dir) + "/", lang="eng", psm=PSM.AUTO)
            self._local.api = api
        return api

    def words(self, image_path: Path) -> list[TessWord]:
        api = self._api()
        with Image.open(image_path) as im:
            api.SetImage(im.convert("L"))
        api.SetSourceResolution(DPI)
        api.Recognize()
        it = api.GetIterator()
        out: list[TessWord] = []
        if it is None:
            return out
        while True:
            text = it.GetUTF8Text(RIL.WORD)
            if text and text.strip():
                x0, y0, x1, y1 = it.BoundingBox(RIL.WORD)
                out.append(TessWord(text.strip(), float(it.Confidence(RIL.WORD)), int(x0), int(y0), int(x1), int(y1)))
            if not it.Next(RIL.WORD):
                break
        return out
