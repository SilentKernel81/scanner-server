"""The assembly sheet: the six steps' renders with their captions, the cut-away with its labels, the notes.
   python compose.py <work folder> <sheet.png>   (the renders are <work folder>/png/step<N>.png; make_sheet.sh runs it)"""
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

folder = Path(sys.argv[1])
sheet_path = Path(sys.argv[2])


def font_file(style):
    """A sans-serif font file of this machine, by fontconfig: Noto Sans if it is there"""
    return subprocess.run(['fc-match', '-f', '%{file}', f'Noto Sans:{style}'], capture_output=True, text=True, check=True).stdout


FONT_FILES = {False: font_file('regular'), True: font_file('bold')}
font = lambda size, bold=False: ImageFont.truetype(FONT_FILES[bold], size)

W = 1800                    # the sheet's width
M = 40                      # margins
INK, GREY, RED = (25, 25, 30), (95, 95, 105), (200, 20, 20)

STEPS = {
    1: ('Press the one-way bearing into the hub',
        "The blue HF0812 goes into the hub's bore (the hub is drawn cut in half). The arrow on its face points out, "
        "toward the block, and shows the way it GRIPS: it must grip when the wheels push the card forward. "
        "Check by hand: hold a piece of rod in it - it turns freely one way and locks the other."),
    2: ('Screw the horn into the hub',
        "Open the servo horn's hole 10 mm from its centre to 2 mm, on both arms. Lay the horn, uncut, in the pocket on "
        "the hub's other face and drive two M2 x 6 self-tapping screws through those holes into the hub. Leave out the "
        "horn's centre screw: once the hub is on, nothing can reach it."),
    3: ('Bearings, rod and wheels in the block',
        "Press the two 608 ball bearings into the block's walls, from outside. Slide the 8 mm rod through them, "
        "threading both wheels on inside the block. Tighten the grub screws on flats filed on the rod. "
        "The rod must turn freely by hand."),
    4: ('The servo into its bracket - from inside',
        "The servo's body goes out through the window; its tabs stay on the bracket's inner face (the block's side). "
        "Two screws through the tabs into the bracket."),
    5: ('The hub onto the rod - BEFORE the bracket',
        "Push the hub, horn facing out, onto the end of the rod: the rod slides into the one-way bearing. "
        "It has to go on now: once the bracket is screwed on, there is no room left to fit it."),
    6: ('The bracket onto the block',
        "Bring the bracket with its servo up to the block: the servo's splined shaft goes into the horn's centre hole. "
        "Screw the bracket's legs on from inside the block (M3)."),
}

LABELS_7 = [                # (text, the point it names in step7.png, where the text goes)
    ('MG90S servo', (120, 520), (40, 770)),
    ('its splined shaft', (300, 462), (150, 840)),
    ('printed hub', (380, 545), (290, 770)),
    ("rod's end - stops inside the bearing", (395, 465), (430, 840)),
    ('block wall', (480, 650), (640, 760)),
    ('servo bracket', (240, 300), (40, 230)),
    ('servo horn (white)', (293, 430), (60, 160)),
    ('one-way bearing HF0812', (405, 428), (250, 110)),
    ('608 ball bearing', (470, 400), (430, 210)),
    ('wheel + O-ring', (600, 300), (760, 150)),
    ('8 mm rod', (780, 440), (820, 330)),
]

NOTES = [
    "There is no stepper motor: each driven axle has a small MG90S servo, and its shaft never touches the 8 mm rod. "
    "The printed hub joins the two, so the size difference doesn't matter.",
    "How it moves: on the forward stroke the servo turns the horn and the hub, the one-way bearing grips the rod, "
    "and the wheels push the card. On the way back the bearing slips and the wheels stand still. "
    "A card can take several strokes.",
    "Why the hub goes on before the bracket: with the bracket on, the gap between the shaft's tip and the bearing "
    "housing is 19.6 mm, the hub is 19 mm long, and the rod sticks 12.5 mm into that gap (from the CAD). "
    "The plan had it the other way round until 2026-10-24, when this sheet was drawn.",
    "Without the centre screw, the hub can slide at most 1 mm along the rod (then it touches the housing), "
    "so the horn can't come off its shaft. Never tried: check that the horn still grips the shaft well.",
    "Never printed or assembled. The sizes come from card_dropper.scad. The servo, horn, bearings and screws are "
    "drawn simplified, so measure yours (servo sizes at the top of the .scad).",
]


def _wrap_exact(draw, xy, text, fnt, width_px, fill, spacing):
    x, y = xy
    line = ''
    for word in text.split():
        trial = (line + ' ' + word).strip()
        if draw.textlength(trial, font=fnt) <= width_px:
            line = trial
        else:
            draw.text((x, y), line, font=fnt, fill=fill)
            y += fnt.size + spacing
            line = word
    if line:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += fnt.size + spacing
    return y


def build():
    col_w = (W - 3 * M) // 2
    pic_h = int(col_w * 900 / 1200)
    cell_h = pic_h + 200
    big_h = int((W - 2 * M) * 900 / 1200)
    H = 200 + 3 * cell_h + 80 + big_h + 520
    sheet = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(sheet)

    d.text((M, 30), 'Card dropper: how a servo turns an 8 mm axle', font=font(46, True), fill=INK)
    d.text((M, 96), 'One driven axle (axle 3; axle 2 is the same), in assembly order. Red arrows: where a part goes.',
           font=font(26), fill=GREY)
    d.line((M, 160, W - M, 160), fill=(210, 210, 215), width=2)

    y0 = 190
    for n, (title, text) in STEPS.items():
        col, row = (n - 1) % 2, (n - 1) // 2
        x, y = M + col * (col_w + M), y0 + row * cell_h
        pic = Image.open(folder / 'png' / f'step{n}.png').resize((col_w, pic_h), Image.LANCZOS)
        sheet.paste(pic, (x, y))
        d.rounded_rectangle((x, y, x + col_w, y + pic_h), radius=10, outline=(215, 215, 222), width=2)
        d.ellipse((x + 14, y + 14, x + 70, y + 70), fill=RED)
        d.text((x + 42, y + 42), str(n), font=font(34, True), fill='white', anchor='mm')
        d.text((x, y + pic_h + 14), title, font=font(30, True), fill=INK)
        _wrap_exact(d, (x, y + pic_h + 56), text, font(22), col_w, fill=GREY, spacing=5)

    # the cut-away, labelled
    y = y0 + 3 * cell_h + 10
    d.text((M, y), 'Assembled, cut along the axle', font=font(34, True), fill=INK)
    d.text((M, y + 48), 'Forward stroke: servo  >  horn  >  hub  >  one-way bearing grips  >  rod  >  wheels.   '
           'Return: the bearing slips, the wheels stand still.', font=font(23), fill=GREY)
    y += 100
    scale = (W - 2 * M) / 1200
    big = Image.open(folder / 'png' / 'step7.png').resize((W - 2 * M, big_h), Image.LANCZOS)
    sheet.paste(big, (M, y))
    d.rounded_rectangle((M, y, W - M, y + big_h), radius=10, outline=(215, 215, 222), width=2)
    lf = font(24, True)
    for text, (px, py), (tx, ty) in LABELS_7:
        p = (M + px * scale, y + py * scale)
        t = (M + tx * scale, y + ty * scale)
        tw = d.textlength(text, font=lf)
        box = (t[0] - 8, t[1] - 6, t[0] + tw + 8, t[1] + lf.size + 10)
        anchor = (min(max(p[0], box[0]), box[2]), box[1] if p[1] < box[1] else box[3] if p[1] > box[3] else (box[1] + box[3]) / 2)
        d.line((anchor, p), fill=INK, width=2)
        d.ellipse((p[0] - 5, p[1] - 5, p[0] + 5, p[1] + 5), fill=RED, outline='white')
        d.rounded_rectangle(box, radius=6, fill='white', outline=INK, width=2)
        d.text(t, text, font=lf, fill=INK)

    # notes
    y += big_h + 40
    d.text((M, y), 'Good to know', font=font(32, True), fill=INK)
    y += 54
    for note in NOTES:
        d.ellipse((M + 4, y + 11, M + 14, y + 21), fill=RED)
        y = _wrap_exact(d, (M + 30, y), note, font(23), W - 2 * M - 30, fill=INK, spacing=5) + 12

    sheet = sheet.crop((0, 0, W, y + 30))
    # 256 colours: a third of the size, and the flat colours and text of a drawing lose nothing visible
    sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(sheet_path, optimize=True)
    print(sheet_path, sheet.size)


build()
