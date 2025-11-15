"""
AI Email Classifier & Meeting Scheduler
Objectives:
1. Classify emails into: Personal, Professional, Spam
2. Auto-detect meetings and add to Google Calendar
"""

import os
import pickle
import base64
import re
from datetime import datetime, timedelta
from email import message_from_bytes
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ============================================
# CONFIGURATION
# ============================================

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.pickle"
TIMEZONE = "Asia/Kolkata"

# ============================================
# GOOGLE AUTHENTICATION
# ============================================

def authenticate_google():
    """Authenticate and return Gmail and Calendar services"""
    creds = None
    
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as token:
            creds = pickle.load(token)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        with open(TOKEN_FILE, "wb") as token:
            pickle.dump(creds, token)
    
    gmail_service = build("gmail", "v1", credentials=creds)
    calendar_service = build("calendar", "v3", credentials=creds)
    
    return gmail_service, calendar_service


# ============================================
# EMAIL FETCHING
# ============================================

def list_unread_emails(gmail_service, max_results=20):
    """Fetch unread emails from Gmail"""
    response = gmail_service.users().messages().list(
        userId="me",
        q="is:unread",
        maxResults=max_results
    ).execute()
    
    return response.get("messages", [])


def get_email_details(gmail_service, msg_id):
    """Get full email details including sender, subject, body"""
    message = gmail_service.users().messages().get(
        userId="me",
        id=msg_id,
        format="raw"
    ).execute()
    
    raw_data = base64.urlsafe_b64decode(message["raw"].encode("ASCII"))
    email_msg = message_from_bytes(raw_data)
    
    sender = email_msg.get("From", "")
    subject = email_msg.get("Subject", "")
    body = extract_body(email_msg)
    
    return {
        "id": msg_id,
        "sender": sender,
        "subject": subject,
        "body": body
    }


def extract_body(email_obj):
    """Extract plain text body from email"""
    if email_obj.is_multipart():
        parts = []
        for part in email_obj.walk():
            if part.get_content_type() == "text/plain":
                try:
                    text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8",
                        errors="replace"
                    )
                    parts.append(text)
                except:
                    continue
        return "\n\n".join(parts)
    else:
        try:
            return email_obj.get_payload(decode=True).decode(
                email_obj.get_content_charset() or "utf-8",
                errors="replace"
            )
        except:
            return ""


# ============================================
# OBJECTIVE 1: EMAIL CLASSIFICATION
# ============================================

# Classification Keywords
SPAM_KEYWORDS = [
    r'\bfree\b', r'\bwin\b', r'\bprize\b', r'\blottery\b',
    r'\bcongratulations\b', r'\bclaim now\b', r'\bclick here\b',
    r'\bunsubscribe\b', r'\boffer\b', r'\bdiscount\b',
    r'\bsave up to\b', r'\bearn points\b', r'\bgrab your offer\b',
    r'\bexclusive deal\b', r'\blimited time\b', r'\bshop now\b',
    r'\bnoreply@\b', r'\bmailers\b', r'\bsurvey\b', r'\brecommendations@\b'
]

PROFESSIONAL_KEYWORDS = [
    r'\bmeeting\b', r'\bproject\b', r'\bdeadline\b', r'\breport\b',
    r'\bproposal\b', r'\bclient\b', r'\bteam\b', r'\bwork\b',
    r'\boffice\b', r'\bpresentation\b', r'\bconference\b',
    r'\bbusiness\b', r'\bschedule\b', r'\bagenda\b'
]

PERSONAL_KEYWORDS = [
    r'\bfamily\b', r'\bfriend\b', r'\bparty\b', r'\bbirthday\b',
    r'\bweekend\b', r'\bdinner\b', r'\blunch\b', r'\bcoffee\b',
    r'\bhow are you\b', r'\bmiss you\b', r'\bcatch up\b'
]


def classify_email(subject, body, sender):
    """
    Classify email into: Personal, Professional, or Spam
    """
    # Combine subject and body for analysis
    text = (subject + " " + body).lower()
    
    # Check for spam first (highest priority)
    spam_count = sum(1 for pattern in SPAM_KEYWORDS if re.search(pattern, text))
    if spam_count >= 2:  # If 2+ spam keywords found
        return "SPAM"
    
    # Check for professional indicators
    prof_count = sum(1 for pattern in PROFESSIONAL_KEYWORDS if re.search(pattern, text))
    
    # Check for personal indicators
    personal_count = sum(1 for pattern in PERSONAL_KEYWORDS if re.search(pattern, text))
    
    # Check sender domain for professional emails
    if re.search(r'@(company|corp|org|edu|gov)', sender.lower()):
        prof_count += 2
    
    # Decision logic
    if prof_count > personal_count:
        return "PROFESSIONAL"
    elif personal_count > 0:
        return "PERSONAL"
    else:
        return "PROFESSIONAL"  # Default to professional if unclear


# ============================================
# OBJECTIVE 2: MEETING DETECTION & CALENDAR
# ============================================

MEETING_KEYWORDS = [
    r'\bmeeting\b', r'\bschedule\b', r'\bcall\b', r'\bappointment\b',
    r'\bconference\b', r'\bdiscussion\b', r'\bcatch up\b',
    r'\blet\'s meet\b', r'\bmeet up\b', r'\bzoom\b', r'\bteams\b',
    r'\binterview\b', r'\bsession\b', r'\bjoin\b.*\b(?:today|tomorrow)\b',
    r'\bwebinar\b', r'\bvirtual meeting\b', r'\bvideo call\b'
]


def detect_meeting(subject, body):
    """Check if email mentions a meeting"""
    text = (subject + " " + body).lower()
    
    for pattern in MEETING_KEYWORDS:
        if re.search(pattern, text):
            return True
    return False


def extract_meeting_time(body):
    """
    Try to extract meeting time from email body
    Returns: datetime object or None
    """
    # Common date/time patterns
    patterns = [
        r'(?:tomorrow|next day)\s+(?:at\s+)?(\d{1,2}:\d{2}\s*(?:am|pm)?)',
        r'(\d{1,2}/\d{1,2}/\d{4})\s+(?:at\s+)?(\d{1,2}:\d{2}\s*(?:am|pm)?)',
        r'(?:on\s+)?(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})',
    ]
    
    # For simplicity, return tomorrow at 10 AM if meeting detected
    # In production, use advanced NLP or regex parsing
    tomorrow = datetime.now() + timedelta(days=1)
    meeting_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    
    return meeting_time


def add_to_calendar(calendar_service, subject, sender, meeting_time, duration_minutes=30):
    """Add meeting event to Google Calendar"""
    start_time = meeting_time
    end_time = start_time + timedelta(minutes=duration_minutes)
    
    event = {
        'summary': f'Meeting: {subject}',
        'description': f'Email from: {sender}',
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': TIMEZONE,
        },
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 30},
            ],
        },
    }
    
    event = calendar_service.events().insert(
        calendarId='primary',
        body=event
    ).execute()
    
    return event.get('htmlLink')


# ============================================
# MAIN PROCESSING FUNCTION
# ============================================

def process_emails():
    """Main function to process emails"""
    print("=" * 60)
    print("AI EMAIL CLASSIFIER & MEETING SCHEDULER")
    print("=" * 60)
    
    # Authenticate
    print("\n[1] Authenticating with Google...")
    gmail_service, calendar_service = authenticate_google()
    print("✓ Authentication successful")
    
    # Fetch unread emails
    print("\n[2] Fetching unread emails...")
    messages = list_unread_emails(gmail_service, max_results=10)
    
    if not messages:
        print("No unread emails found.")
        return
    
    print(f"✓ Found {len(messages)} unread email(s)")
    
    # Process each email
    results = []
    
    for idx, msg in enumerate(messages, 1):
        print(f"\n{'=' * 60}")
        print(f"Processing Email {idx}/{len(messages)}")
        print(f"{'=' * 60}")
        
        # Get email details
        email = get_email_details(gmail_service, msg["id"])
        
        print(f"\nFrom: {email['sender']}")
        print(f"Subject: {email['subject']}")
        print(f"Body Preview: {email['body'][:100]}...")
        
        # OBJECTIVE 1: Classify email
        category = classify_email(
            email['subject'],
            email['body'],
            email['sender']
        )
        print(f"\n📧 Classification: {category}")
        
        # OBJECTIVE 2: Detect meeting and add to calendar
        has_meeting = detect_meeting(email['subject'], email['body'])
        calendar_link = None
        
        if has_meeting:
            print("\n📅 Meeting detected!")
            meeting_time = extract_meeting_time(email['body'])
            print(f"   Suggested time: {meeting_time.strftime('%Y-%m-%d %H:%M')}")
            
            # Ask user confirmation
            confirm = input("   Add to calendar? (yes/no): ").lower()
            
            if confirm == 'yes':
                calendar_link = add_to_calendar(
                    calendar_service,
                    email['subject'],
                    email['sender'],
                    meeting_time
                )
                print(f"   ✓ Meeting added to calendar")
                print(f"   Link: {calendar_link}")
            else:
                print("   Meeting not added to calendar")
        
        # Store results
        results.append({
            'sender': email['sender'],
            'subject': email['subject'],
            'category': category,
            'has_meeting': has_meeting,
            'calendar_link': calendar_link
        })
    
    # Summary
    print("\n" + "=" * 60)
    print("PROCESSING COMPLETE - SUMMARY")
    print("=" * 60)
    
    for idx, result in enumerate(results, 1):
        print(f"\n{idx}. {result['subject'][:40]}...")
        print(f"   Category: {result['category']}")
        if result['has_meeting']:
            print(f"   📅 Meeting: {'Added to calendar' if result['calendar_link'] else 'Not added'}")
    
    # Statistics
    print("\n" + "-" * 60)
    personal = sum(1 for r in results if r['category'] == 'PERSONAL')
    professional = sum(1 for r in results if r['category'] == 'PROFESSIONAL')
    spam = sum(1 for r in results if r['category'] == 'SPAM')
    meetings = sum(1 for r in results if r['has_meeting'])
    
    print(f"Personal: {personal} | Professional: {professional} | Spam: {spam}")
    print(f"Meetings detected: {meetings}")
    print("=" * 60)


# ============================================
# RUN THE PROGRAM
# ============================================

if __name__ == "__main__":
    try:
        process_emails()
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("\nMake sure you have:")
        print("1. credentials.json file in the same folder")
        print("2. Enabled Gmail and Calendar API in Google Cloud Console")