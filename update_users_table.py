"""
این فایل برای به‌روزرسانی جدول users و افزودن فیلد role استفاده می‌شود
"""
import logging
from app import app, db

# تنظیم لاگر
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                  level=logging.INFO)
logger = logging.getLogger(__name__)

def add_role_column():
    """
    افزودن ستون role به جدول users
    """
    try:
        with app.app_context():
            # اجرای کوئری SQL برای افزودن ستون جدید
            db.session.execute(db.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'student' NOT NULL"))
            db.session.commit()
            
            # ثبت کاربران ادمین موجود
            db.session.execute(db.text("UPDATE users SET role = 'admin' WHERE username = 'admin'"))
            
            # ثبت کاربران انباردار موجود
            db.session.execute(db.text("UPDATE users SET role = 'warehouse_manager' WHERE username = 'warehouse_manager' OR username = 'anbar'"))
            
            db.session.commit()
            
            logger.info("ستون role با موفقیت به جدول users افزوده شد.")
            return True
            
    except Exception as e:
        logger.error(f"خطا در افزودن ستون role: {str(e)}")
        return False

if __name__ == "__main__":
    if add_role_column():
        print("عملیات به‌روزرسانی جدول users با موفقیت انجام شد.")
    else:
        print("خطا در به‌روزرسانی جدول users. به لاگ‌ها مراجعه کنید.")