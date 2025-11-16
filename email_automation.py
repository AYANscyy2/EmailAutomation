"""
===============================================================================
COMPLETE AI EMAIL AUTOMATION SYSTEM 
===============================================================================

Features:
1. Email Classification (Personal, Professional, Spam)
2. Meeting Detection & Calendar Integration
3. AI-Powered Reply Generation with Google Gemini
4. Smart Email Drafting with Tone Adjustment
5. User Approval Workflow

AI Model: Google Gemini 2.5 Flash
Author: AI Email Automation Team
Date: November 2025
===============================================================================
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

# Google Gemini for AI
import google.generativeai as genai


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

# Gemini API Configuration
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')


# ============================================
# TONE ENGINE - Smart Tone Adjustment
# ============================================

class ToneEngine:
    """Manages email tone based on recipient type and formality level"""
    
    def __init__(self):
        # Base tone presets for different recipient types
        self.base_tones = {
            "friend": {
                "style": "casual, warm, relaxed, humorous if appropriate",
                "greeting": "Hey",
                "signoff": "Cheers"
            },
            "colleague": {
                "style": "professional, respectful, concise",
                "greeting": "Hi",
                "signoff": "Best regards"
            },
            "relative": {
                "style": "personal, warm, caring, gentle",
                "greeting": "Hi",
                "signoff": "Take care"
            },
            "student": {
                "style": "clear, encouraging, supportive",
                "greeting": "Hello",
                "signoff": "Warm regards"
            },
            "client": {
                "style": "polished, courteous, confident, solution-oriented",
                "greeting": "Hello",
                "signoff": "Kind regards"
            },
            "boss": {
                "style": "formal, respectful, clear, professional",
                "greeting": "Dear",
                "signoff": "Respectfully"
            }
        }
    
    def blend(self, base_style, formality):
        """
        Blend tone based on formality:
        0.0 → very casual
        1.0 → very formal
        """
        casual_modifiers = [
            "casual", "relaxed", "friendly", "approachable",
            "light-hearted", "informal"
        ]
        
        formal_modifiers = [
            "formal", "professional", "polished", "respectful",
            "structured", "concise"
        ]
        
        blended = f"{base_style}, "
        
        if formality < 0.33:
            blended += ", ".join(casual_modifiers)
        elif formality > 0.66:
            blended += ", ".join(formal_modifiers)
        else:
            blended += "balanced tone (between casual and formal)"
        
        return blended
    
    def get_tone_profile(self, recipient_type, formality=0.5):
        """Get complete tone profile for a recipient"""
        profile = self.base_tones.get(recipient_type, self.base_tones["colleague"])
        return {
            "greeting": profile["greeting"],
            "signoff": profile["signoff"],
            "style": self.blend(profile["style"], formality)
        }


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
# EMAIL FETCHING & PROCESSING
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
        "body": body,
        "email_object": email_msg
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
# EMAIL CLASSIFICATION
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

MEETING_KEYWORDS = [
    r'\bmeeting\b', r'\bschedule\b', r'\bcall\b', r'\bappointment\b',
    r'\bconference\b', r'\bdiscussion\b', r'\bcatch up\b',
    r'\blet\'s meet\b', r'\bmeet up\b', r'\bzoom\b', r'\bteams\b',
    r'\binterview\b', r'\bsession\b', r'\bjoin\b.*\b(?:today|tomorrow)\b',
    r'\bwebinar\b', r'\bvirtual meeting\b', r'\bvideo call\b'
]


def classify_email(subject, body, sender):
    """Classify email into: Personal, Professional, or Spam"""
    text = (subject + " " + body).lower()
    
    # Check for spam first
    spam_count = sum(1 for pattern in SPAM_KEYWORDS if re.search(pattern, text))
    if spam_count >= 2:
        return "SPAM"
    
    # Check for professional indicators
    prof_count = sum(1 for pattern in PROFESSIONAL_KEYWORDS if re.search(pattern, text))
    
    # Check for personal indicators
    personal_count = sum(1 for pattern in PERSONAL_KEYWORDS if re.search(pattern, text))
    
    # Check sender domain
    if re.search(r'@(company|corp|org|edu|gov)', sender.lower()):
        prof_count += 2
    
    # Decision logic
    if prof_count > personal_count:
        return "PROFESSIONAL"
    elif personal_count > 0:
        return "PERSONAL"
    else:
        return "PROFESSIONAL"


def detect_meeting(subject, body):
    """Check if email mentions a meeting"""
    text = (subject + " " + body).lower()
    
    for pattern in MEETING_KEYWORDS:
        if re.search(pattern, text):
            return True
    return False


# ============================================
# GEMINI AI - REPLY GENERATION
# ============================================

def initialize_gemini():
    """Initialize Gemini with API key"""
    if not GEMINI_API_KEY:
        print("\n⚠️  Warning: GEMINI_API_KEY not set!")
        print("   Set it with: export GEMINI_API_KEY='your-key-here'")
        return False
    
    genai.configure(api_key=GEMINI_API_KEY)
    return True


def generate_reply_with_gemini(original_email, reply_context, recipient_type, formality=0.5):
    """Generate AI-powered email reply using Google Gemini"""
    
    if not initialize_gemini():
        return generate_template_reply(original_email, reply_context, recipient_type, formality)
    
    tone_engine = ToneEngine()
    tone_profile = tone_engine.get_tone_profile(recipient_type, formality)
    
    prompt = f"""You are an AI email assistant. Generate a professional email reply.

Original Email:
Subject: {original_email['subject']}
From: {original_email['sender']}
Body: {original_email['body'][:500]}

Task: {reply_context}

Requirements:
- Tone: {tone_profile['style']}
- Keep it 3-5 sentences
- Be professional and natural
- Write ONLY the email body text (no greeting or signoff)

Generate the email body now:"""
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        email_body = response.text.strip()
        
        # Format complete email
        full_reply = f"{tone_profile['greeting']},\n\n{email_body}\n\n{tone_profile['signoff']}"
        
        return {
            "greeting": tone_profile['greeting'],
            "body": email_body,
            "signoff": tone_profile['signoff'],
            "full_text": full_reply,
            "tone": tone_profile['style']
        }
    
    except Exception as e:
        print(f"   ⚠️  Gemini error: {e}")
        return generate_template_reply(original_email, reply_context, recipient_type, formality)


def generate_template_reply(original_email, reply_context, recipient_type, formality=0.5):
    """Generate template-based reply (fallback)"""
    
    tone_engine = ToneEngine()
    tone_profile = tone_engine.get_tone_profile(recipient_type, formality)
    
    # Simple template-based reply
    if "thank" in reply_context.lower():
        body = "Thank you for your email. I appreciate you reaching out. I'll review this and get back to you shortly."
    elif "meeting" in reply_context.lower():
        body = "Thank you for the meeting invite. I'd be happy to join. Please let me know the time that works best for you."
    elif "question" in reply_context.lower():
        body = "Thanks for your question. I'll look into this and provide you with detailed information soon."
    else:
        body = f"Thank you for your email. I've received your message and will respond appropriately."
    
    full_reply = f"{tone_profile['greeting']},\n\n{body}\n\n{tone_profile['signoff']}"
    
    return {
        "greeting": tone_profile['greeting'],
        "body": body,
        "signoff": tone_profile['signoff'],
        "full_text": full_reply,
        "tone": tone_profile['style']
    }


def generate_new_email_with_gemini(context, recipient_type, formality=0.5):
    """Generate a new email from scratch using Gemini"""
    
    if not initialize_gemini():
        return generate_template_email(context, recipient_type, formality)
    
    tone_engine = ToneEngine()
    tone_profile = tone_engine.get_tone_profile(recipient_type, formality)
    
    prompt = f"""You are an AI email assistant. Generate a professional email.

Context: {context}

Requirements:
- Tone: {tone_profile['style']}
- Keep it clear and concise (3-5 sentences)
- Be professional and natural
- Write ONLY the email body text (no greeting or signoff)

Generate the email body now:"""
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        response = model.generate_content(prompt)
        body = response.text.strip()
    except Exception as e:
        print(f"   ⚠️  Gemini error: {e}")
        body = f"Regarding: {context}\n\nI wanted to reach out to discuss this matter with you. Please let me know your thoughts."
    
    full_email = f"{tone_profile['greeting']},\n\n{body}\n\n{tone_profile['signoff']}"
    
    return {
        "greeting": tone_profile['greeting'],
        "body": body,
        "signoff": tone_profile['signoff'],
        "full_text": full_email,
        "tone": tone_profile['style']
    }


def generate_template_email(context, recipient_type, formality=0.5):
    """Generate template email (fallback)"""
    
    tone_engine = ToneEngine()
    tone_profile = tone_engine.get_tone_profile(recipient_type, formality)
    
    body = f"Regarding: {context}\n\nI wanted to reach out to discuss this matter with you. Please let me know your thoughts."
    full_email = f"{tone_profile['greeting']},\n\n{body}\n\n{tone_profile['signoff']}"
    
    return {
        "greeting": tone_profile['greeting'],
        "body": body,
        "signoff": tone_profile['signoff'],
        "full_text": full_email,
        "tone": tone_profile['style']
    }


# ============================================
# EMAIL SENDING
# ============================================

def create_email_message(to, subject, body_text):
    """Create email message for sending"""
    mime = MIMEText(body_text)
    mime["To"] = to
    mime["Subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    return {"raw": raw}


def send_email(gmail_service, raw_message):
    """Send email via Gmail API"""
    return gmail_service.users().messages().send(
        userId="me", 
        body=raw_message
    ).execute()


# ============================================
# CALENDAR INTEGRATION
# ============================================

def extract_meeting_time(body):
    """Extract meeting time from email"""
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
# MAIN WORKFLOW FUNCTIONS
# ============================================

def process_incoming_emails():
    """Main function to process incoming emails"""
    
    print("=" * 70)
    print("AI EMAIL AUTOMATION - PROCESS INCOMING EMAILS")
    print("=" * 70)
    
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
        print(f"\n{'=' * 70}")
        print(f"Processing Email {idx}/{len(messages)}")
        print(f"{'=' * 70}")
        
        # Get email details
        email = get_email_details(gmail_service, msg["id"])
        
        print(f"\nFrom: {email['sender']}")
        print(f"Subject: {email['subject']}")
        print(f"Body Preview: {email['body'][:100]}...")
        
        # Classify email
        category = classify_email(
            email['subject'],
            email['body'],
            email['sender']
        )
        print(f"\n📧 Classification: {category}")
        
        # Detect meeting
        has_meeting = detect_meeting(email['subject'], email['body'])
        calendar_link = None
        
        if has_meeting:
            print("\n📅 Meeting detected!")
            meeting_time = extract_meeting_time(email['body'])
            print(f"   Suggested time: {meeting_time.strftime('%Y-%m-%d %H:%M')}")
            
            confirm = input("   Add to calendar? (yes/no): ").lower()
            
            if confirm == 'yes':
                calendar_link = add_to_calendar(
                    calendar_service,
                    email['subject'],
                    email['sender'],
                    meeting_time
                )
                print(f"   ✓ Meeting added to calendar")
        
        # Generate reply (skip spam)
        if category != "SPAM":
            reply_offer = input("\n   Generate AI reply? (yes/no): ").lower()
            
            if reply_offer == 'yes':
                print("\n   Recipient types:")
                print("   1. friend  2. colleague  3. client  4. boss  5. relative")
                
                recipient_type = input("   Select (1-5): ")
                type_map = {"1": "friend", "2": "colleague", "3": "client", "4": "boss", "5": "relative"}
                recipient_type = type_map.get(recipient_type, "colleague")
                
                formality = float(input("   Formality (0.0=casual, 1.0=formal): "))
                reply_context = input("   What should the reply say?: ")
                
                print("\n   ⏳ Generating reply with Gemini...")
                reply = generate_reply_with_gemini(email, reply_context, recipient_type, formality)
                
                print("\n   " + "─" * 60)
                print("   GENERATED REPLY:")
                print("   " + "─" * 60)
                print(f"\n{reply['full_text']}\n")
                print("   " + "─" * 60)
                
                send_confirm = input("\n   Send this reply? (yes/no): ").lower()
                
                if send_confirm == 'yes':
                    sender_email = re.search(r'<(.+?)>', email['sender'])
                    if sender_email:
                        sender_email = sender_email.group(1)
                    else:
                        sender_email = email['sender']
                    
                    msg = create_email_message(
                        sender_email,
                        f"Re: {email['subject']}",
                        reply['full_text']
                    )
                    send_email(gmail_service, msg)
                    print("   ✓ Reply sent!")
        
        results.append({
            'sender': email['sender'],
            'subject': email['subject'],
            'category': category,
            'has_meeting': has_meeting,
            'calendar_link': calendar_link
        })
    
    # Summary
    print("\n" + "=" * 70)
    print("PROCESSING COMPLETE - SUMMARY")
    print("=" * 70)
    
    for idx, result in enumerate(results, 1):
        print(f"\n{idx}. {result['subject'][:50]}...")
        print(f"   Category: {result['category']}")
        if result['has_meeting']:
            print(f"   📅 Meeting: {'Added' if result['calendar_link'] else 'Not added'}")
    
    # Statistics
    print("\n" + "-" * 70)
    personal = sum(1 for r in results if r['category'] == 'PERSONAL')
    professional = sum(1 for r in results if r['category'] == 'PROFESSIONAL')
    spam = sum(1 for r in results if r['category'] == 'SPAM')
    meetings = sum(1 for r in results if r['has_meeting'])
    
    print(f"Personal: {personal} | Professional: {professional} | Spam: {spam}")
    print(f"Meetings detected: {meetings}")
    print("=" * 70)


def compose_new_email_workflow():
    """Workflow for composing a new email"""
    
    print("\n" + "=" * 70)
    print("COMPOSE NEW EMAIL WITH GEMINI AI")
    print("=" * 70)
    
    print("\nRecipient types:")
    print("1. friend  2. colleague  3. client  4. boss  5. relative")
    
    recipient_type = input("\nSelect (1-5): ")
    type_map = {"1": "friend", "2": "colleague", "3": "client", "4": "boss", "5": "relative"}
    recipient_type = type_map.get(recipient_type, "colleague")
    
    formality = float(input("Formality (0.0=casual, 1.0=formal): "))
    context = input("What should the email be about?: ")
    
    print("\n⏳ Generating email with Gemini...")
    email = generate_new_email_with_gemini(context, recipient_type, formality)
    
    print("\n" + "─" * 70)
    print("GENERATED EMAIL:")
    print("─" * 70)
    print(f"\n{email['full_text']}\n")
    print("─" * 70)
    
    print("\nOptions:")
    print("1. Send email")
    print("2. Edit and send")
    print("3. Regenerate")
    print("4. Cancel")
    
    choice = input("\nYour choice (1-4): ")
    
    if choice == "1":
        to_address = input("Recipient email: ")
        subject = input("Email subject: ")
        msg = create_email_message(to_address, subject, email['full_text'])
        
        gmail_service, _ = authenticate_google()
        send_email(gmail_service, msg)
        print("\n✓ Email sent!")
    
    elif choice == "2":
        print("\nEnter your edited version:")
        edited = input()
        to_address = input("Recipient email: ")
        subject = input("Email subject: ")
        msg = create_email_message(to_address, subject, edited)
        
        gmail_service, _ = authenticate_google()
        send_email(gmail_service, msg)
        print("\n✓ Email sent!")
    
    elif choice == "3":
        compose_new_email_workflow()
    
    else:
        print("\nEmail cancelled.")


# ============================================
# MAIN MENU
# ============================================

def main():
    """Main application entry point"""
    
    print("\n" + "=" * 70)
    print("AI EMAIL AUTOMATION SYSTEM")
    print("Powered by Google Gemini 2.5 Flash")
    print("=" * 70)
    
    # Check Gemini availability
    if GEMINI_API_KEY:
        print("🤖 AI Model: Google Gemini 2.5 Flash (FREE) ✓")
    else:
        print("⚠️  GEMINI_API_KEY not set - AI features will use templates")
        print("   Set with: export GEMINI_API_KEY='your-key'")
    
    print("\nSelect an option:")
    print("1. Process incoming emails (classify + meetings + AI replies)")
    print("2. Compose new email with Gemini AI")
    print("3. Exit")
    
    choice = input("\nYour choice (1-3): ")
    
    if choice == "1":
        process_incoming_emails()
    
    elif choice == "2":
        compose_new_email_workflow()
    
    elif choice == "3":
        print("\nGoodbye!")
        return
    
    else:
        print("\nInvalid choice. Please try again.")
        main()
    
    # Ask if user wants to continue
    continue_choice = input("\n\nDo something else? (yes/no): ").lower()
    if continue_choice == 'yes':
        main()
    else:
        print("\nThank you for using AI Email Automation System!")


# ============================================
# RUN THE PROGRAM
# ============================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProgram interrupted by user. Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("\nMake sure you have:")
        print("1. credentials.json file")
        print("2. Gmail & Calendar APIs enabled")
        print("3. GEMINI_API_KEY environment variable set")
        print("   Get key: https://makersuite.google.com/app/apikey")
        print("   Set with: export GEMINI_API_KEY='your-key-here'")