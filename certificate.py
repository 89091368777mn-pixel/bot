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
    regular = next((p for p in regular_paths if Path(p).exists()), None)
    bold = next((p for p in bold_paths if Path(p).exists()), regular)
    if not regular:
        raise RuntimeError("Не найден TTF-шрифт с поддержкой кириллицы")
    pdfmetrics.registerFont(TTFont("CertFont", regular))
    pdfmetrics.registerFont(TTFont("CertFont-Bold", bold))
    return "CertFont", "CertFont-Bold"


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
    font, font_bold = _register_fonts()

    if not filename:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in recipient)[:40]
        filename = f"cert_{safe}.pdf"

    out_path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))

    # Фон
    _draw_background(c)

    # Полупрозрачная плашка слева для читаемости текста
    c.setFillColorRGB(1, 1, 1)
    c.setFillAlpha(0.72)
    c.roundRect(36, 480, 340, 360, 18, fill=1, stroke=0)
    c.setFillAlpha(1)

    # Заголовок
    c.setFillColorRGB(0.15, 0.12, 0.2)
    c.setFont(font_bold, 20)
    c.drawCentredString(206, 800, "ПОДАРОЧНЫЙ СЕРТИФИКАТ")

    c.setStrokeColorRGB(0.55, 0.45, 0.25)
    c.setLineWidth(1.2)
    c.line(70, 788, 340, 788)

    def label_value(label: str, value: str, y: float):
        c.setFillColorRGB(0.35, 0.32, 0.4)
        c.setFont(font, 11)
        c.drawString(55, y + 22, label)
        c.setFillColorRGB(0.12, 0.1, 0.16)
        c.setFont(font_bold, 15)
        c.drawString(55, y, value)
        c.setStrokeColorRGB(0.7, 0.65, 0.55)
        c.setLineWidth(0.6)
        c.line(55, y - 6, 350, y - 6)

    label_value("Кому", recipient, 740)
    label_value("Вид массажа", massage_type, 680)
    label_value("Количество массажей", quantity, 620)
    label_value("Срок действия", valid_until, 560)

    # Подпись массажиста
    c.setFillColorRGB(0.2, 0.18, 0.25)
    c.setFont(font, 10)
    c.drawString(55, 510, "Ваш массажист")
    c.setFont(font_bold, 12)
    c.drawString(55, 494, THERAPIST)

    # Нижний блок с контактами на тёмном фоне
    c.setFillColorRGB(0, 0, 0)
    c.setFillAlpha(0.45)
    c.rect(0, 0, PAGE_W, 70, fill=1, stroke=0)
    c.setFillAlpha(1)

    c.setFillColorRGB(1, 1, 1)
    c.setFont(font, 10)
    c.drawCentredString(PAGE_W / 2, 42, "Свяжитесь, чтобы договориться о сеансе")
    c.setFont(font_bold, 13)
    c.drawCentredString(PAGE_W / 2, 24, PHONE)
    c.setFont(font, 9)
    c.drawCentredString(PAGE_W / 2, 10, ADDRESS)

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
