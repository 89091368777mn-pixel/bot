from pathlib import Path
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
ASSETS = Path(__file__).parent / &quot;assets&quot;
BG_PATH = ASSETS / &quot;cert_bg.jpg&quot;
OUTPUT_DIR = Path(__file__).parent / &quot;certificates&quot;
OUTPUT_DIR.mkdir(exist_ok=True)
PAGE_W = 633
PAGE_H = 897

def register_font():
font_path = &quot;/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf&quot;
bold_path = &quot;/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf&quot;
if not Path(font_path).exists():
raise RuntimeError(&quot;Не найден кириллический шрифт DejaVuSans&quot;)
pdfmetrics.registerFont(TTFont(&quot;DejaVu&quot;, font_path))
if Path(bold_path).exists():
pdfmetrics.registerFont(TTFont(&quot;DejaVuBold&quot;, bold_path))
return &quot;DejaVu&quot;, &quot;DejaVuBold&quot;
return &quot;DejaVu&quot;, &quot;DejaVu&quot;

def generate_certificate(
recipient: str,
massage_type: str,
quantity: str,
valid_until: str,
filename: str | None = None,
) -&gt; Path:
font, font_bold = register_font()
if not BG_PATH.exists():
raise FileNotFoundError(

f&quot;Не найден фон сертификата: {BG_PATH}&quot;
)
if not filename:
safe_name = &quot;&quot;.join(
c if c.isalnum() or c in &quot;-_&quot; else &quot;_&quot;
for c in recipient
)[:40]
filename = f&quot;cert_{safe_name}.pdf&quot;
output_path = OUTPUT_DIR / filename
pdf = canvas.Canvas(
str(output_path),
pagesize=(PAGE_W, PAGE_H),
)
# Оригинальный сертификат на всю страницу
pdf.drawImage(
ImageReader(str(BG_PATH)),
0,
0,
width=PAGE_W,
height=PAGE_H,
preserveAspectRatio=False,
)
# Цвет текста
pdf.setFillColorRGB(1, 1, 1)
# ------------------------------
# КОМУ
# ------------------------------
pdf.setFont(font_bold, 15)
pdf.drawString(
145,
560,
recipient,
)
# ------------------------------
# ВИД МАССАЖА
# ------------------------------
pdf.setFont(font, 14)

pdf.drawString(
145,
515,
massage_type,
)
# ------------------------------
# КОЛИЧЕСТВО
# ------------------------------
pdf.setFont(font, 14)
pdf.drawString(
145,
470,
quantity,
)
# ------------------------------
# СРОК ДЕЙСТВИЯ
# ------------------------------
pdf.setFont(font, 14)
pdf.drawString(
145,
425,
valid_until,
)
pdf.save()
return output_path

if __name__ == &quot;__main__&quot;:
result = generate_certificate(
recipient=&quot;Иванов Александр&quot;,
massage_type=&quot;Массаж будущего&quot;,
quantity=&quot;1 сеанс&quot;,
valid_until=&quot;до 30.12.2026&quot;,
)
print(result)
