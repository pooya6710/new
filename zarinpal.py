import requests
import logging
import os
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class ZarinPal:
    """
    کلاس ارتباط با درگاه پرداخت زرین‌پال
    """
    def __init__(self, merchant_id=None, sandbox=True):
        """
        راه‌اندازی کلاس زرین‌پال
        
        Parameters:
            merchant_id (str): کد پذیرنده زرین‌پال (به صورت پیش‌فرض از متغیر محیطی ZARINPAL_MERCHANT_ID خوانده می‌شود)
            sandbox (bool): استفاده از محیط آزمایشی (sandbox) یا محیط واقعی
        """
        self.merchant_id = merchant_id or os.environ.get('ZARINPAL_MERCHANT_ID')
        if not self.merchant_id:
            logger.warning('کد پذیرنده (Merchant ID) زرین‌پال تنظیم نشده است!')
        
        # تنظیم آدرس‌های API با توجه به حالت فعلی (sandbox یا واقعی)
        if sandbox:
            self.api_base_url = 'https://sandbox.zarinpal.com/pg/v4/payment/'
            self.payment_url = 'https://sandbox.zarinpal.com/pg/StartPay/'
        else:
            self.api_base_url = 'https://api.zarinpal.com/pg/v4/payment/'
            self.payment_url = 'https://www.zarinpal.com/pg/StartPay/'
    
    def request_payment(self, amount, description, callback_url, email=None, phone=None):
        """
        درخواست ایجاد یک پرداخت جدید
        
        Parameters:
            amount (int): مبلغ به تومان (حداقل 1000 تومان)
            description (str): توضیحات پرداخت
            callback_url (str): آدرس بازگشت پس از پرداخت
            email (str): ایمیل خریدار (اختیاری)
            phone (str): شماره موبایل خریدار (اختیاری)
        
        Returns:
            dict: نتیجه درخواست به صورت دیکشنری
        """
        if not self.merchant_id:
            return {
                'success': False,
                'message': 'کد پذیرنده (Merchant ID) تنظیم نشده است!'
            }
        
        try:
            # بررسی حداقل مبلغ
            if amount < 1000:
                return {
                    'success': False,
                    'message': 'حداقل مبلغ پرداخت 1000 تومان است'
                }
            
            # ساخت درخواست به API زرین‌پال
            request_url = urljoin(self.api_base_url, 'request.json')
            data = {
                'merchant_id': self.merchant_id,
                'amount': amount,  # مبلغ به تومان
                'description': description,
                'callback_url': callback_url
            }
            
            # اضافه کردن اطلاعات اختیاری
            if email:
                data['email'] = email
            if phone:
                data['phone'] = phone
            
            response = requests.post(request_url, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200 and result.get('data', {}).get('code', -1) == 100:
                authority = result['data']['authority']
                payment_url = f"{self.payment_url}{authority}"
                return {
                    'success': True,
                    'authority': authority,
                    'payment_url': payment_url
                }
            else:
                error_code = result.get('errors', {}).get('code', 0)
                error_message = result.get('errors', {}).get('message', 'خطای نامشخص در ارتباط با درگاه پرداخت')
                logger.error(f"ZarinPal Error: {error_code} - {error_message}")
                return {
                    'success': False,
                    'error_code': error_code,
                    'message': error_message
                }
                
        except Exception as e:
            logger.error(f"خطا در ارتباط با زرین‌پال: {str(e)}")
            return {
                'success': False,
                'message': f"خطا در ارتباط با درگاه پرداخت: {str(e)}"
            }
    
    def verify_payment(self, authority, amount):
        """
        تایید یک پرداخت انجام شده
        
        Parameters:
            authority (str): کد یکتای تراکنش دریافت شده از زرین‌پال
            amount (int): مبلغ پرداخت به تومان
        
        Returns:
            dict: نتیجه تایید به صورت دیکشنری
        """
        if not self.merchant_id:
            return {
                'success': False,
                'message': 'کد پذیرنده (Merchant ID) تنظیم نشده است!'
            }
        
        try:
            # ساخت درخواست تایید پرداخت
            verify_url = urljoin(self.api_base_url, 'verify.json')
            data = {
                'merchant_id': self.merchant_id,
                'amount': amount,  # مبلغ به تومان 
                'authority': authority
            }
            
            response = requests.post(verify_url, json=data, timeout=10)
            result = response.json()
            
            if response.status_code == 200 and result.get('data', {}).get('code', -1) == 100:
                # تراکنش موفق
                ref_id = result['data']['ref_id']
                return {
                    'success': True,
                    'ref_id': ref_id,
                    'message': 'پرداخت با موفقیت انجام شد'
                }
            else:
                # تراکنش ناموفق
                error_code = result.get('errors', {}).get('code', 0)
                error_message = result.get('errors', {}).get('message', 'خطای نامشخص در تایید پرداخت')
                logger.error(f"ZarinPal Verify Error: {error_code} - {error_message}")
                return {
                    'success': False,
                    'error_code': error_code,
                    'message': error_message
                }
                
        except Exception as e:
            logger.error(f"خطا در تایید پرداخت زرین‌پال: {str(e)}")
            return {
                'success': False,
                'message': f"خطا در تایید پرداخت: {str(e)}"
            }
