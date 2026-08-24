from pathlib import Path

from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


BASE_DIR = Path(__file__).resolve().parent

ASSETS = BASE_DIR / "assets"
BG_PATH = ASSETS / "cert_bg.jpg"

OUTPUT_DIR = BASE_DIR / "certificates"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PAGE_W = 633
PAGE_H = 897


def register_font():
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

    if not Path(font_path).exists():
        raise RuntimeError(
            "Не найден кириллический шрифт DejaVuSans"
        )

    pdfmetrics.registerFont(
        TTFont("DejaVu", font_path)
    )

    if Path(bold_path).exists():
        pdfmetrics.registerFont(
            TTFont("DejaVuBold", bold_path)
        )
        return "DejaVu", "DejaVuBold"

    return "DejaVu", "DejaVu"


def generate_certificate(
    recipient: str,
    massage_type: str,
    quantity: str,
    valid_until: str,
    filename: str | None = None,
) -> Path:

    font, font_bold = register_font()

    if not BG_PATH.exists():
        raise FileNotFoundError(
            f"Не найден фон сертификата: {BG_PATH}"
        )

    if not filename:
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_"
            for c in recipient
        )[:40]

        filename = f"cert_{safe_name}.pdf"

    output_path = OUTPUT_DIR / filename

    pdf = canvas.Canvas(
        str(output_path),
        pagesize=(PAGE_W, PAGE_H),
    )

    # Фон сертификата
    pdf.drawImage(
        ImageReader(str(BG_PATH)),
        0,
        0,
        width=PAGE_W,
        height=PAGE_H,
        preserveAspectRatio=False,
    )

    # Белый текст
    pdf.setFillColorRGB(1, 1, 1)

    # КОМУ
    pdf.setFont(font_bold, 15)
    pdf.drawString(
        145,
        560,
        recipient,
    )

    # ВИД МАССАЖА
    pdf.setFont(font, 14)
    pdf.drawString(
        145,
        515,
        massage_type,
    )

    # КОЛИЧЕСТВО
    pdf.setFont(font, 14)
    pdf.drawString(
        145,
        470,
        quantity,
    )

    # СРОК ДЕЙСТВИЯ
    pdf.setFont(font, 14)
    pdf.drawString(
        145,
        425,
        valid_until,
    )

    pdf.save()

    return output_path


if __name__ == "__main__":
    result = generate_certificate(
        recipient="Иванов Александр",
        massage_type="Массаж будущего",
        quantity="1 сеанс",
        valid_until="до 30.12.2026",
    )

    print(f"Сертификат создан: {result}")
