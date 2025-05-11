import os
import jdatetime
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import inch, mm

# تعریف و ثبت فونت‌های فارسی - اگر فونت‌ها در پوشه فونت‌ها وجود دارند
FONTS_FOLDER = os.path.join(os.getcwd(), 'static', 'fonts')
os.makedirs(FONTS_FOLDER, exist_ok=True)

def setup_persian_fonts():
    """تنظیم فونت‌های فارسی برای استفاده در ReportLab"""
    # بررسی وجود فونت‌ها و ثبت آنها
    try:
        # اگر فونت‌ها در سیستم وجود ندارند، از فونت‌های پیش‌فرض استفاده می‌کنیم
        font_path = os.path.join(FONTS_FOLDER, 'Vazir.ttf')
        if not os.path.exists(font_path):
            # از فونت استاندارد استفاده می‌کنیم
            return False
            
        # ثبت فونت‌های فارسی
        pdfmetrics.registerFont(TTFont('Vazir', font_path))
        pdfmetrics.registerFont(TTFont('Vazir-Bold', os.path.join(FONTS_FOLDER, 'Vazir-Bold.ttf')))
        return True
    except Exception as e:
        print(f"خطا در تنظیم فونت‌های فارسی: {str(e)}")
        return False

def generate_inventory_report_pdf(items, filename):
    """تولید گزارش PDF برای موجودی انبار"""
    # تنظیم فونت‌های فارسی
    persian_fonts_available = setup_persian_fonts()
    
    # تنظیم استایل‌ها
    styles = getSampleStyleSheet()
    
    # افزودن استایل‌های فارسی اگر فونت‌های فارسی در دسترس باشند
    if persian_fonts_available:
        styles.add(ParagraphStyle(name='Title_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=16,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=12))
        
        styles.add(ParagraphStyle(name='Heading_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=14,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=10))
        
        styles.add(ParagraphStyle(name='Normal_FA', 
                                 fontName='Vazir',
                                 fontSize=10,
                                 alignment=0,  # راست‌چین
                                 spaceAfter=6))
        
        title_style = styles['Title_FA']
        heading_style = styles['Heading_FA']
        normal_style = styles['Normal_FA']
    else:
        # استفاده از استایل‌های پیش‌فرض
        title_style = styles['Title']
        heading_style = styles['Heading1']
        normal_style = styles['Normal']
    
    # ایجاد سند PDF
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # محتوای گزارش
    content = []
    
    # عنوان گزارش
    content.append(Paragraph("گزارش موجودی انبار", title_style))
    content.append(Spacer(1, 10*mm))
    
    # تاریخ گزارش
    current_date = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    content.append(Paragraph(f"تاریخ گزارش: {current_date}", normal_style))
    content.append(Spacer(1, 10*mm))
    
    # جدول موجودی
    table_data = [["کد", "نام کالا", "دسته‌بندی", "واحد", "موجودی", "حداقل موجودی", "وضعیت"]]
    
    for item in items:
        status_text = ""
        if item.status == "normal":
            status_text = "عادی"
        elif item.status == "low":
            status_text = "کم"
        elif item.status == "out":
            status_text = "ناموجود"
            
        table_data.append([
            item.code,
            item.name,
            item.category if item.category else "",
            item.unit,
            str(item.quantity),
            str(item.min_quantity),
            status_text
        ])
    
    # ایجاد جدول
    table = Table(table_data, repeatRows=1)
    
    # استایل جدول
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # افزودن استایل‌های وضعیت
    for i, row in enumerate(table_data[1:], 1):
        status = row[-1]
        if status == "کم":
            table_style.add('TEXTCOLOR', (6, i), (6, i), colors.orange)
            table_style.add('FONTNAME', (6, i), (6, i), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold')
        elif status == "ناموجود":
            table_style.add('TEXTCOLOR', (6, i), (6, i), colors.red)
            table_style.add('FONTNAME', (6, i), (6, i), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold')
    
    table.setStyle(table_style)
    content.append(table)
    
    # افزودن خلاصه آماری
    content.append(Spacer(1, 10*mm))
    content.append(Paragraph("خلاصه آماری:", heading_style))
    content.append(Spacer(1, 5*mm))
    
    total_items = len(items)
    low_items = sum(1 for item in items if item.status == "low")
    out_items = sum(1 for item in items if item.status == "out")
    normal_items = total_items - low_items - out_items
    
    stats_data = [
        ["تعداد کل اقلام", str(total_items)],
        ["اقلام با موجودی عادی", str(normal_items)],
        ["اقلام با موجودی کم", str(low_items)],
        ["اقلام ناموجود", str(out_items)]
    ]
    
    stats_table = Table(stats_data)
    stats_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (0, -1), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
    ]))
    
    content.append(stats_table)
    
    # ایجاد PDF
    doc.build(content)
    
    return filename

def generate_transaction_report_pdf(transactions, filename, start_date=None, end_date=None):
    """تولید گزارش PDF برای تراکنش‌های انبار"""
    # تنظیم فونت‌های فارسی
    persian_fonts_available = setup_persian_fonts()
    
    # تنظیم استایل‌ها
    styles = getSampleStyleSheet()
    
    # افزودن استایل‌های فارسی اگر فونت‌های فارسی در دسترس باشند
    if persian_fonts_available:
        styles.add(ParagraphStyle(name='Title_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=16,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=12))
        
        styles.add(ParagraphStyle(name='Heading_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=14,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=10))
        
        styles.add(ParagraphStyle(name='Normal_FA', 
                                 fontName='Vazir',
                                 fontSize=10,
                                 alignment=0,  # راست‌چین
                                 spaceAfter=6))
        
        title_style = styles['Title_FA']
        heading_style = styles['Heading_FA']
        normal_style = styles['Normal_FA']
    else:
        # استفاده از استایل‌های پیش‌فرض
        title_style = styles['Title']
        heading_style = styles['Heading1']
        normal_style = styles['Normal']
    
    # ایجاد سند PDF
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # محتوای گزارش
    content = []
    
    # عنوان گزارش
    content.append(Paragraph("گزارش تراکنش‌های انبار", title_style))
    content.append(Spacer(1, 10*mm))
    
    # تاریخ گزارش
    current_date = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    content.append(Paragraph(f"تاریخ گزارش: {current_date}", normal_style))
    
    # بازه زمانی گزارش
    if start_date and end_date:
        date_range = f"از {start_date} تا {end_date}"
    elif start_date:
        date_range = f"از {start_date} تا کنون"
    elif end_date:
        date_range = f"تا {end_date}"
    else:
        date_range = "تمام تاریخ‌ها"
        
    content.append(Paragraph(f"بازه زمانی: {date_range}", normal_style))
    content.append(Spacer(1, 10*mm))
    
    # جدول تراکنش‌ها
    table_data = [["#", "تاریخ", "نام کالا", "کد کالا", "نوع تراکنش", "مقدار", "موجودی قبلی", "موجودی فعلی", "کاربر"]]
    
    for i, transaction in enumerate(transactions, 1):
        # تبدیل تاریخ به شمسی
        jalali_date = jdatetime.datetime.fromgregorian(datetime=transaction.timestamp).strftime("%Y/%m/%d %H:%M")
        
        # تبدیل نوع تراکنش به فارسی
        transaction_type = ""
        if transaction.transaction_type == "add":
            transaction_type = "افزایش"
        elif transaction.transaction_type == "remove":
            transaction_type = "کاهش"
        elif transaction.transaction_type == "adjust":
            transaction_type = "تنظیم"
            
        table_data.append([
            str(i),
            jalali_date,
            transaction.item.name,
            transaction.item.code,
            transaction_type,
            str(transaction.quantity),
            str(transaction.previous_quantity),
            str(transaction.current_quantity),
            transaction.user.username if transaction.user else ""
        ])
    
    # ایجاد جدول
    table = Table(table_data, repeatRows=1)
    
    # استایل جدول
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # افزودن استایل‌های نوع تراکنش
    for i, row in enumerate(table_data[1:], 1):
        transaction_type = row[4]
        if transaction_type == "افزایش":
            table_style.add('TEXTCOLOR', (4, i), (4, i), colors.green)
        elif transaction_type == "کاهش":
            table_style.add('TEXTCOLOR', (4, i), (4, i), colors.red)
    
    table.setStyle(table_style)
    content.append(table)
    
    # افزودن خلاصه آماری
    content.append(Spacer(1, 10*mm))
    content.append(Paragraph("خلاصه آماری:", heading_style))
    content.append(Spacer(1, 5*mm))
    
    total_transactions = len(transactions)
    add_transactions = sum(1 for t in transactions if t.transaction_type == "add")
    remove_transactions = sum(1 for t in transactions if t.transaction_type == "remove")
    adjust_transactions = sum(1 for t in transactions if t.transaction_type == "adjust")
    
    stats_data = [
        ["تعداد کل تراکنش‌ها", str(total_transactions)],
        ["تراکنش‌های افزایش", str(add_transactions)],
        ["تراکنش‌های کاهش", str(remove_transactions)],
        ["تراکنش‌های تنظیم", str(adjust_transactions)]
    ]
    
    stats_table = Table(stats_data)
    stats_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (0, -1), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
    ]))
    
    content.append(stats_table)
    
    # ایجاد PDF
    doc.build(content)
    
    return filename

def generate_food_usage_forecast_pdf(food_usage_data, filename):
    """تولید گزارش PDF برای پیش‌بینی مصرف مواد غذایی"""
    # تنظیم فونت‌های فارسی
    persian_fonts_available = setup_persian_fonts()
    
    # تنظیم استایل‌ها
    styles = getSampleStyleSheet()
    
    # افزودن استایل‌های فارسی اگر فونت‌های فارسی در دسترس باشند
    if persian_fonts_available:
        styles.add(ParagraphStyle(name='Title_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=16,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=12))
        
        styles.add(ParagraphStyle(name='Heading_FA', 
                                 fontName='Vazir-Bold',
                                 fontSize=14,
                                 alignment=1,  # وسط‌چین
                                 spaceAfter=10))
        
        styles.add(ParagraphStyle(name='Normal_FA', 
                                 fontName='Vazir',
                                 fontSize=10,
                                 alignment=0,  # راست‌چین
                                 spaceAfter=6))
        
        title_style = styles['Title_FA']
        heading_style = styles['Heading_FA']
        normal_style = styles['Normal_FA']
    else:
        # استفاده از استایل‌های پیش‌فرض
        title_style = styles['Title']
        heading_style = styles['Heading1']
        normal_style = styles['Normal']
    
    # ایجاد سند PDF
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=20*mm,
        leftMargin=20*mm,
        topMargin=20*mm,
        bottomMargin=20*mm
    )
    
    # محتوای گزارش
    content = []
    
    # عنوان گزارش
    content.append(Paragraph("پیش‌بینی مصرف مواد غذایی", title_style))
    content.append(Spacer(1, 10*mm))
    
    # تاریخ گزارش
    current_date = jdatetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    content.append(Paragraph(f"تاریخ گزارش: {current_date}", normal_style))
    content.append(Spacer(1, 10*mm))
    
    # جدول پیش‌بینی‌ها
    table_data = [["نام غذا", "نام ماده اولیه", "تعداد پرس", "مقدار مصرف هر پرس", "مقدار کل مورد نیاز", "موجودی فعلی", "وضعیت"]]
    
    for item in food_usage_data:
        status_text = ""
        status_color = colors.black
        
        if item['status'] == "ok":
            status_text = "کافی"
            status_color = colors.green
        elif item['status'] == "warning":
            status_text = "کم"
            status_color = colors.orange
        elif item['status'] == "critical":
            status_text = "ناکافی"
            status_color = colors.red
            
        table_data.append([
            item['food_name'],
            item['item_name'],
            str(item['portions']),
            str(item['quantity_per_serving']),
            str(item['total_needed']),
            str(item['current_quantity']),
            status_text
        ])
    
    # ایجاد جدول
    table = Table(table_data, repeatRows=1)
    
    # استایل جدول
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Vazir-Bold' if persian_fonts_available else 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    # افزودن استایل‌های وضعیت
    for i, row in enumerate(table_data[1:], 1):
        status = row[-1]
        if status == "کافی":
            table_style.add('TEXTCOLOR', (6, i), (6, i), colors.green)
        elif status == "کم":
            table_style.add('TEXTCOLOR', (6, i), (6, i), colors.orange)
        elif status == "ناکافی":
            table_style.add('TEXTCOLOR', (6, i), (6, i), colors.red)
    
    table.setStyle(table_style)
    content.append(table)
    
    # افزودن نکات و توضیحات
    content.append(Spacer(1, 10*mm))
    content.append(Paragraph("نکات و توضیحات:", heading_style))
    content.append(Spacer(1, 5*mm))
    
    notes = [
        "اقلام با وضعیت «ناکافی» نیاز فوری به تأمین دارند.",
        "اقلام با وضعیت «کم» در آینده نزدیک نیاز به تأمین خواهند داشت.",
        "این گزارش بر اساس آمار رزروهای فعلی و میزان مصرف هر پرس غذا تهیه شده است."
    ]
    
    for note in notes:
        content.append(Paragraph(f"• {note}", normal_style))
        content.append(Spacer(1, 2*mm))
    
    # ایجاد PDF
    doc.build(content)
    
    return filename