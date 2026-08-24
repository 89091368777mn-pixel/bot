"""
Генерация подарочного сертификата PDF.
Фон — из вашего макета, поверх — поля и данные.
"""

from pathlib import Path

from pdfrw import PdfReader
from pdfrw.buildxobj import pagexobj
from pdfrw.toreportlab import makerl
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ASSETS = Path(__file__).parent / "assets"
BG_PDF_PATH = ASSETS / "cert_bg.pdf"
BG_IMAGE_PATH = ASSETS / "cert_bg.jpg"
OUTPUT_DIR = Path(__file__).parent / "certificates"
OUTPUT_DIR.mkdir(exist_ok=True)

PAGE_W = 633
PAGE_H = 897

THERAPIST = "Новосёлов Михаил Сергеевич"
PHONE = "+7 (999) 656-12-34"
ADDRESS = "ул. Несебрская, 4, Сочи"


def _register_fonts():
    regular_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ]
    italic_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansOblique.ttf",
        "C:/Windows/Fonts/ariali.ttf",
        "C:/Windows/Fonts/segoeuii.ttf",
    ]
    bold_italic_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBoldOblique.ttf",
        "C:/Windows/Fonts/arialbi.ttf",
        "C:/Windows/Fonts/segoeuiz.ttf",
    ]
    regular = next((p for p in regular_paths if Path(p).exists()), None)
    bold = next((p for p in bold_paths if Path(p).exists()), regular)
    italic = next((p for p in italic_paths if Path(p).exists()), regular)
    bold_italic = next((p for p in bold_italic_paths if Path(p).exists()), italic)
    if not regular:
        raise RuntimeError("Не найден TTF-шрифт с поддержкой кириллицы")
    pdfmetrics.registerFont(TTFont("CertFont", regular))
    pdfmetrics.registerFont(TTFont("CertFont-Bold", bold))
    pdfmetrics.registerFont(TTFont("CertFont-Italic", italic))
    pdfmetrics.registerFont(TTFont("CertFont-BoldItalic", bold_italic))
    return "CertFont", "CertFont-Bold", "CertFont-Italic", "CertFont-BoldItalic"


def _draw_background(c: canvas.Canvas):
    if BG_PDF_PATH.exists():
        page = PdfReader(str(BG_PDF_PATH)).pages[0]
        xobj = pagexobj(page)
        c.saveState()
        c.translate(0, 0)
        c.scale(PAGE_W / float(xobj.BBox[2]), PAGE_H / float(xobj.BBox[3]))
        c.doForm(makerl(c, xobj))
        c.restoreState()
        return

    if BG_IMAGE_PATH.exists():
        c.drawImage(
            ImageReader(str(BG_IMAGE_PATH)),
            0, 0, width=PAGE_W, height=PAGE_H,
            preserveAspectRatio=True, anchor="c",
        )
        return

    c.setFillColorRGB(0.1, 0.08, 0.15)
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)


def generate_certificate(
    recipient: str,
    massage_type: str,
    quantity: str,
    valid_until: str,
    filename: str | None = None,
) -> Path:
    """
    Создаёт PDF-сертификат.

    recipient     — имя получателя
    massage_type  — вид массажа
    quantity      — например «3 сеанса»
    valid_until   — например «до 31.12.2026»
    """
    font, font_bold, font_italic, font_bold_italic = _register_fonts()

    if not filename:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in recipient)[:40]
        filename = f"cert_{safe}.pdf"

    out_path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))

    # Фон
    _draw_background(c)

    def fitted_size(text: str, font_name: str, size: float, max_width: float) -> float:
        while size > 9 and pdfmetrics.stringWidth(text, font_name, size) > max_width:
            size -= 0.5
        return size

    def text_shadow(
        text: str,
        x: float,
        y: float,
        size: float,
        font_name: str,
        color=(1, 1, 1),
        max_width: float = 510,
    ):
        size = fitted_size(text, font_name, size, max_width)
        c.setFont(font_name, size)
        c.setFillColorRGB(0, 0, 0)
        c.setFillAlpha(0.8)
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            c.drawCentredString(x + dx, y + dy, text)
        c.setFillAlpha(1)
        c.setFillColorRGB(*color)
        c.drawCentredString(x, y, text)

    def field(label: str, value: str, y: float, value_size: float = 15):
        text_shadow(label, PAGE_W / 2, y + 15, 9, font_italic, (0.93, 0.84, 0.67))
        text_shadow(value, PAGE_W / 2, y - 4, value_size, font_bold_italic)

    # 0.5 cm = 14.17 pt: title and underline move up together.
    text_shadow("ПОДАРОЧНЫЙ СЕРТИФИКАТ", PAGE_W / 2, 818.2, 22, font_bold_italic)
    c.setStrokeColorRGB(0.78, 0.65, 0.34)
    c.setLineWidth(1.4)
    c.line(148, 804.2, PAGE_W - 148, 804.2)

    field("Кому", recipient, 700)
    field("Вид массажа", massage_type, 660)
    field("Количество массажей", quantity, 572)

    # Нижний блок с контактами на тёмном фоне
    c.setFillColorRGB(0, 0, 0)
    c.setFillAlpha(0.45)
    c.rect(0, 0, PAGE_W, 108, fill=1, stroke=0)
    c.setFillAlpha(1)

    text_shadow("Ваш массажист", PAGE_W / 2, 132, 9, font_italic, (0.93, 0.84, 0.67))
    text_shadow(THERAPIST, PAGE_W / 2, 114, 13, font_bold_italic)
    text_shadow("Срок действия сертификата", PAGE_W / 2, 88, 8.5, font_italic, (0.93, 0.84, 0.67))
    text_shadow(valid_until, PAGE_W / 2, 70, 11.5, font_bold_italic)
    text_shadow("Свяжитесь, чтобы договориться о сеансе", PAGE_W / 2, 48, 9, font_italic)
    text_shadow(PHONE, PAGE_W / 2, 28, 11, font_bold_italic)
    text_shadow(ADDRESS, PAGE_W / 2, 12, 8, font_italic)

    c.save()
    return out_path


if __name__ == "__main__":
    path = generate_certificate(
        recipient="Анна Иванова",
        massage_type="Массаж будущего",
        quantity="3 сеанса",
        valid_until="до 31.12.2026",
    )
    print("Created:", path)
