"""
این فایل برای اجرای مهاجرت از SQLite به PostgreSQL استفاده می‌شود.
"""
import logging
import sys
from migrations import migrate_to_postgresql

# تنظیم لاگر
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                  level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logger.info("شروع مهاجرت به PostgreSQL...")
    result = migrate_to_postgresql()
    
    if result:
        logger.info("مهاجرت به PostgreSQL با موفقیت انجام شد.")
        sys.exit(0)
    else:
        logger.error("خطا در مهاجرت به PostgreSQL!")
        sys.exit(1)