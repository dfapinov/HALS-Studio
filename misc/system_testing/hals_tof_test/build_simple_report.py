"""Build the concise report from the latest analyze_test.py results and graphs."""
from pathlib import Path
import json
from datetime import date
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
M=json.loads((HERE/'simple_results.json').read_text())
OUT=ROOT/'output/pdf'; OUT.mkdir(parents=True,exist_ok=True)
if Path('C:/Windows/Fonts/arial.ttf').exists():
    pdfmetrics.registerFont(TTFont('Report','C:/Windows/Fonts/arial.ttf'))
    pdfmetrics.registerFont(TTFont('ReportBold','C:/Windows/Fonts/arialbd.ttf'))
else:
    from reportlab.pdfbase.pdfmetrics import Font
    pdfmetrics.registerFont(Font('Report','Helvetica','WinAnsiEncoding'))
    pdfmetrics.registerFont(Font('ReportBold','Helvetica-Bold','WinAnsiEncoding'))
pdfmetrics.registerFontFamily('Report',normal='Report',bold='ReportBold')
styles={
 'body':ParagraphStyle('body',fontName='Report',fontSize=10.5,leading=14,spaceAfter=8),
 'title':ParagraphStyle('title',fontName='ReportBold',fontSize=23,leading=27,spaceAfter=10),
 'h1':ParagraphStyle('h1',fontName='ReportBold',fontSize=16,leading=20,spaceAfter=10),
 'h2':ParagraphStyle('h2',fontName='ReportBold',fontSize=11.5,leading=15,spaceBefore=6,spaceAfter=7),
 'small':ParagraphStyle('small',fontName='Report',fontSize=9,leading=12,spaceAfter=7),
 'caption':ParagraphStyle('caption',fontName='Report',fontSize=8.5,leading=11,textColor=colors.HexColor('#444444'),spaceAfter=8),
 'cell':ParagraphStyle('cell',fontName='Report',fontSize=9.5,leading=12),
 'head':ParagraphStyle('head',fontName='ReportBold',fontSize=9.5,leading=12,textColor=colors.white)}
story=[]; W=A4[0]-88
def p(s,style='body'): story.append(Paragraph(s,styles[style]))
def img(name,width=W):
    path=HERE/'simple_graphs'/f'{name}.png'; iw,ih=ImageReader(str(path)).getSize()
    story.append(Image(str(path),width=width,height=width*ih/iw))
def table(rows,widths):
    t=Table([[Paragraph(str(v),styles['head' if i==0 else 'cell']) for v in row] for i,row in enumerate(rows)],colWidths=widths)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#24485c')),
      ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f0f5f7')]),
      ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#d9d9d9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
      ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
      ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.append(t); story.append(Spacer(1,10))
def page(): story.append(PageBreak())

p('Does HALS preserve sound travel time','title')
p('A simple Stage 5 test with a synthetic point source','h2')
p('Move a virtual microphone upwards by 500 mm. Sound now travels along a slightly longer diagonal path. Does the exported phase show exactly the extra delay we expect?')
img('geometry',W*.91)
p('<b>Coordinates R, Phi, Z:</b> R is the horizontal distance from the vertical Z axis. Phi is the angle around that axis, with 0° pointing forward along +X. Z is height. Here both microphones have R = 2 m and Phi = 0°; their heights are Z = 0 and Z = 0.5 m.','small')
p('Table 1  Effect of the 500 mm height offset','h2')
table([['Quantity','Geometry predicts','HALS export measures'],
 ['Path length',f'{M["expected_path_mm"]:.6f} mm',f'{M["measured_path_mm"]:.6f} mm'],
 ['Delay',f'{M["expected_delay_us"]:.6f} µs',f'{M["measured_delay_us"]:.6f} µs'],
 ['Phase slope per kHz',f'{M["expected_slope_deg_khz"]:.6f}°',f'{M["measured_slope_deg_khz"]:.6f}°']], [W*.31,W*.345,W*.345])
p('Values describe the change from Mic A to Mic B, measured over <b>20 Hz to 20 kHz</b>.','caption')
p(f'<b>Geometry versus HALS delay error: {abs(M["error_us"]):.6f} µs</b>, equivalent to <b>{abs(M["error_mm"]):.6f} mm</b> of sound travel.','small')
p(f'<b>Largest phase error in the Mic B minus Mic A comparison: {M["max_phase_error_deg"]:.3f}° across 20 Hz to 20 kHz.</b>','small')
p('The geometry in three steps','h2')
p('<b>1. Distance:</b> Pythagoras gives √(2² + 0.5²) = <b>2.061552813 m</b>.<br/><b>2. Travel time:</b> 2.061552813 ÷ 343 = <b>6010.358055 µs</b>.<br/><b>3. Extra travel time relative to Mic A:</b><br/>(2.061552813 - 2) ÷ 343 = <b>179.454265 µs</b>.','small')
p('At 1 kHz, one cycle takes 1 ms and represents 360°. The extra delay is 0.179454 of that cycle, giving <b>64.6035° of phase lag per kHz</b> after subtracting the common 2 m travel time.','small')

page(); p('The phase plots confirm the geometry','h1')
p('<b>Ref Origin TOF subtraction removes the same 2 m travel time from both microphones.</b> Mic A then sits near zero phase. Mic B keeps the extra delay caused by its greater distance. Its phase follows the geometric prediction.')
img('reference_phase',W*.97)
p('Mic B and the prediction overlap. The downward slope is the expected extra travel time.','caption')
p('A closer look at the difference','h2')
img('differential_phase',W*.97)
p('The exported phase difference between Mic B and Mic A, minus the geometric prediction. The vertical scale is magnified to reveal the remaining error.','caption')
p('What does the tiny difference mean','h2')
p(f'Across 20 Hz to 20 kHz, the error in the extra travel time is <b>{abs(M["error_us"]):.6f} µs</b> (about {abs(M["error_ns"]):.3f} nanoseconds), equivalent to <b>{abs(M["error_mm"]):.6f} mm</b> of travel. The generator, solved model and exporter all use <b>343 m/s</b>, so this is not a mismatch between their sound-speed settings.')
p('The small remaining difference can include sampling, model-fitting and export-rounding effects. The match remains close across the full audible range.')
p(f'The direct complex frequency-domain output (NPZ) and the text response (FRD) give extra delays that differ by only <b>{abs(M["npz_frd_difference_ns"]):.3f} nanoseconds</b>. Both agree closely with the geometric prediction.')
p('<b>Result:</b> HALS preserves the expected extra sound travel time in this two-position synthetic test.')

page(); p('Test setup and how to repeat it','h1')
p('The test folder <b>misc/system_testing/hals_tof_test</b> already contains <b>synth_ir_gen_tof_test.py</b>, configured with radius 0 and one source point. It generates a full range omnidirectional source using the accompanying <b>synth_ir_grid.csv</b>, which contains <b>1,443 measurement positions</b>.')
table([['Setting','Value for this test'],
 ['Synthetic source','Centre (0, 0, 0) m; radius 0 m; piston count 1'],
 ['Sound speed','343 m/s in the generator, solve and export'],
 ['Stage 4 solve','Maximum order N8; origin fixed at (0, 0, 0)'],
 ['Use optimised origins','Off for the test; no origin shifts in the solved model'],
 ['Stage 5 Advanced settings','Manual IR capture padding: 0 samples'],
 ['Stage 5 microphone settings','2 m radius; theta 90°; phi 0°; Z offset 0 then 500 mm'],
 ['Stage 5 response settings','Internal field; Ref Origin TOF; no mic calibration']], [W*.38,W*.62])
p('<b>Generator:</b> radius zero places the single source point exactly at the origin.','small')
p('<b>Stage 5:</b> capture padding must be zero because the synthetic generator adds no leading capture padding to the IRs.','small')
p('How well did Stage 4 fit the synthetic measurements','h2')
img('stage4_fit_error',W*.94)
p('Saved Stage 4 fit error across the measured grid. Lower is better: -60 dB means the remaining error is 0.1% of the measured response level. This checks the model fit, separately from the travel-time test.','caption')
p(f'Across 20 Hz to 20 kHz, the median fit error is <b>{M["stage4_fit_percent_median"]:.3f}%</b> and the maximum is <b>{M["stage4_fit_percent_max"]:.3f}%</b>. N8 is the upper limit; this solve uses orders 2 to 8 as frequency increases.','small')
p('Repeat the test','h2')
p('Open a terminal in <b>misc/system_testing/hals_tof_test</b>. Run <b>synth_ir_gen_tof_test.py</b> to generate the WAVs, then import them into HALS and solve using the settings above. To test the solved model, run:','small')
p('<font face="Courier" size="8">python export_test.py --coeff "path/to/your_model.h5"<br/>python analyze_test.py</font>','small')
p('Omit <b>--coeff</b> to use the existing model in this test folder. The first script exports both microphones; the second creates the metrics and all report graphs. See the local README for the full instructions.','small')

def footer(canvas,doc):
    canvas.setFont('Report',8); canvas.setFillColor(colors.HexColor('#555555'))
    canvas.drawString(44,25,'HALS Stage 5 point source test | '+date.today().strftime('%d %B %Y'))
    canvas.drawRightString(A4[0]-44,25,str(doc.page))
path=OUT/'HALS_Stage5_Synthetic_Phase_Validation_Updated.pdf'
SimpleDocTemplate(str(path),pagesize=A4,leftMargin=44,rightMargin=44,topMargin=37,bottomMargin=42,
    title='HALS Stage 5 Point Source Travel Time Test',author='HALS project').build(story,onFirstPage=footer,onLaterPages=footer)
print(path)
