"""
این فایل برای ایجاد حساب کاربری مدیر در صورت عدم وجود استفاده می‌شود
"""
import logging
from werkzeug.security import generate_password_hash
from app import db, app
from models import User

logger = logging.getLogger(__name__)

def create_admin_user():
    """ایجاد کاربر مدیر در صورت عدم وجود"""
    try:
        with app.app_context():
            # بررسی وجود کاربر مدیر
            admin_exists = User.query.filter_by(username='admin').first()
            
            if not admin_exists:
                # ایجاد کاربر مدیر با رمز عبور پیش‌فرض
                admin_user = User(
                    username='admin',
                    password=generate_password_hash('admin123')
                )
                db.session.add(admin_user)
                db.session.commit()
                logger.info("کاربر مدیر با موفقیت ایجاد شد.")
                return True
            else:
                logger.info("کاربر مدیر از قبل وجود دارد.")
                return False
    except Exception as e:
        logger.error(f"خطا در ایجاد کاربر مدیر: {str(e)}")
        return False

if __name__ == "__main__":
    # تنظیم لاگر
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                      level=logging.INFO)
    
    # ایجاد کاربر مدیر
    create_admin_user()