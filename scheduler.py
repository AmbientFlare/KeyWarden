# scheduler.py
import threading
import time
import logging
import schedule
from datetime import datetime
from typing import Dict, Any


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class EmailScheduler:
    """
    A simple scheduler for email-related tasks
    """
    def __init__(self, db_session_maker):
        """
        Initialize the scheduler with a session maker
        
        Args:
            db_session_maker: Function that creates a new database session
        """
        self.db_session_maker = db_session_maker
        self.stop_event = threading.Event()
        self.scheduler_thread = None
    
    def start(self):
        """Start the scheduler thread"""
        if self.scheduler_thread is not None and self.scheduler_thread.is_alive():
            logger.warning("Scheduler is already running")
            return
        
        self.stop_event.clear()
        self.scheduler_thread = threading.Thread(target=self._run_scheduler)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()
        logger.info("Email scheduler started")
    
    def stop(self):
        """Stop the scheduler thread"""
        if self.scheduler_thread is None or not self.scheduler_thread.is_alive():
            logger.warning("Scheduler is not running")
            return
        
        self.stop_event.set()
        self.scheduler_thread.join(timeout=5)
        logger.info("Email scheduler stopped")
    
    def _run_scheduler(self):
        """Run the scheduler loop"""
        # Schedule tasks
        self._schedule_tasks()
        
        # Run the scheduler loop
        while not self.stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)
    
    def _schedule_tasks(self):
        """Schedule all email-related tasks"""
        # Check for expiring licenses daily at 8:00 AM
        schedule.every().day.at("08:00").do(self._check_expiring_licenses)
        
        # Send weekly report every Monday at 7:00 AM
        schedule.every().monday.at("07:00").do(self._send_weekly_report)
        
        # Send monthly report on the 1st of every month at 7:00 AM
        # Fix: schedule.every().month does not exist, use a daily job with a condition
        schedule.every().day.at("07:00").do(self._check_and_send_monthly_report)
    
    def _check_and_send_monthly_report(self):
        """Check if today is the first day of the month and send monthly report if it is"""
        today = datetime.now()
        
        # Only run on the first day of the month
        if today.day == 1:
            logger.info(f"Today is the first day of the month. Running monthly report.")
            self._send_monthly_report()
        else:
            logger.debug(f"Today is not the first day of the month. Skipping monthly report.")
            
    def _check_expiring_licenses(self):
        """Check for licenses that are about to expire and send warnings"""
        logger.info("Running expiration check task")
        
        try:
            # Create a new database session
            db = self.db_session_maker()
            
            # Import here to avoid circular imports
            from email_integration import check_and_send_expiration_warnings
            
            # Check and send warnings
            results = check_and_send_expiration_warnings(db)
            
            # Log results
            total_sent = sum(results.values())
            logger.info(f"Expiration check complete. Sent {total_sent} expiration warnings")
            for days, count in results.items():
                if count > 0:
                    logger.info(f"- {count} warnings for {days}")
        
        except Exception as e:
            logger.error(f"Error in expiration check task: {str(e)}")
        
        finally:
            # Close the database session
            if 'db' in locals():
                db.close()
    
    def _send_weekly_report(self):
        """Send weekly license usage report to admin"""
        logger.info("Running weekly report task")
        
        try:
            # Create a new database session
            db = self.db_session_maker()
            
            # Get report frequency setting
            from db import crud
            system_settings = crud.get_system_settings_dict(db)
            report_frequency = system_settings.get("email_report_frequency", "never")
            
            # Only send if weekly reports are enabled
            if report_frequency != "weekly":
                logger.info("Weekly reports disabled. Skipping.")
                return
            
            # Import here to avoid circular imports
            from email_integration import send_admin_usage_report
            
            # Send report
            success = send_admin_usage_report(db, "weekly")
            
            if success:
                logger.info("Weekly report sent successfully")
            else:
                logger.warning("Failed to send weekly report")
        
        except Exception as e:
            logger.error(f"Error in weekly report task: {str(e)}")
        
        finally:
            # Close the database session
            if 'db' in locals():
                db.close()
    
    def _send_monthly_report(self):
        """Send monthly license usage report to admin"""
        logger.info("Running monthly report task")
        
        try:
            # Create a new database session
            db = self.db_session_maker()
            
            # Get report frequency setting
            from db import crud
            system_settings = crud.get_system_settings_dict(db)
            report_frequency = system_settings.get("email_report_frequency", "never")
            
            # Only send if monthly reports are enabled
            if report_frequency != "monthly":
                logger.info("Monthly reports disabled. Skipping.")
                return
            
            # Import here to avoid circular imports
            from email_integration import send_admin_usage_report
            
            # Send report
            success = send_admin_usage_report(db, "monthly")
            
            if success:
                logger.info("Monthly report sent successfully")
            else:
                logger.warning("Failed to send monthly report")
        
        except Exception as e:
            logger.error(f"Error in monthly report task: {str(e)}")
        
        finally:
            # Close the database session
            if 'db' in locals():
                db.close()