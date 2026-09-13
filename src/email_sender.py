import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime
from src.auth import authenticate_gmail
from src.config import RECIPIENT_EMAIL

class EmailSender:
    def __init__(self, creds=None):
        self.creds = creds or authenticate_gmail()
        self.service = build('gmail', 'v1', credentials=self.creds)

    def build_html_digest(self, relevant_articles, total_fetched, date_str):
        """
        Builds a beautiful, premium HTML template for the daily news digest.
        """
        # Count articles by country
        kr_count = sum(1 for a in relevant_articles if a['country'] == 'KR')
        jp_count = sum(1 for a in relevant_articles if a['country'] == 'JP')
        
        # Build articles HTML
        articles_html = ""
        
        if not relevant_articles:
            articles_html = f"""
            <div style="background-color: #ffffff; border-radius: 12px; padding: 30px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 20px;">
                <div style="font-size: 48px; margin-bottom: 15px;">🔍</div>
                <h3 style="margin-top: 0; color: #1e293b; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">No Relevant Articles Found</h3>
                <p style="color: #64748b; font-size: 15px; line-height: 1.6; margin-bottom: 0;">
                    We evaluated <strong>{total_fetched}</strong> articles from South Korea and Japan, but none matched the AIFOD filtering criteria for today. We will keep scanning!
                </p>
            </div>
            """
        else:
            for art in relevant_articles:
                country_badge = ""
                if art['country'] == 'KR':
                    country_badge = '<span style="background-color: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;">🇰🇷 South Korea</span>'
                else:
                    country_badge = '<span style="background-color: #fee2e2; color: #b91c1c; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;">🇯🇵 Japan</span>'
                
                # Format ISO datetime if possible
                pub_date = art['published']
                try:
                    dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                    date_display = dt.strftime("%b %d, %H:%M UTC")
                except:
                    date_display = pub_date

                # Fetch optional AIFOD fields
                insight = art.get('aifod_insight', '')
                question = art.get('aifod_question', '')
                answer = art.get('aifod_suggested_answer', '')
                
                insight_html = ""
                if insight:
                    insight_html = f"""
                    <div style="background-color: #f5f3ff; border-left: 4px solid #8b5cf6; padding: 12px 14px; border-radius: 0 8px 8px 0; margin-bottom: 16px;">
                        <div style="color: #6d28d9; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">AIFOD Strategic Insight</div>
                        <p style="margin: 0; color: #4c1d95; font-size: 13px; font-family: 'Plus Jakarta Sans', Arial, sans-serif; line-height: 1.5;">
                            {insight}
                        </p>
                    </div>
                    """
                
                qa_html = ""
                if question and answer:
                    qa_html = f"""
                    <div style="background-color: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 14px; margin-top: 16px;">
                        <div style="color: #166534; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">Practitioner Q&A & Stance</div>
                        <div style="margin-bottom: 8px;">
                            <strong style="color: #166534; font-size: 13px; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">Q: {question}</strong>
                        </div>
                        <div style="color: #14532d; font-size: 13px; font-family: 'Plus Jakarta Sans', Arial, sans-serif; line-height: 1.5; padding-left: 14px; border-left: 2px solid #86efac; font-style: italic;">
                            <strong>AIFOD Stance:</strong> {answer}
                        </div>
                    </div>
                    """
                    
                articles_html += f"""
                <div style="background-color: #ffffff; border-radius: 12px; padding: 24px; margin-bottom: 24px; box-shadow: 0 4px 10px rgba(0,0,0,0.04); border: 1px solid #e2e8f0; text-align: left;">
                    <!-- Badge & Meta info -->
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                        {country_badge}
                        <span style="color: #94a3b8; font-size: 12px; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">
                            {art['source']} &bull; {date_display}
                        </span>
                    </div>
                    
                    <!-- Article Title -->
                    <h3 style="margin: 0 0 10px 0; font-size: 18px; line-height: 1.4; font-family: 'Plus Jakarta Sans', Arial, sans-serif; font-weight: 700;">
                        <a href="{art['link']}" target="_blank" style="color: #1e3a8a; text-decoration: none;">{art['english_title']}</a>
                    </h3>
                    
                    <p style="color: #94a3b8; font-size: 11px; margin: 0 0 16px 0; font-family: 'Plus Jakarta Sans', Arial, sans-serif; font-style: italic;">
                        Original: {art['original_title']}
                    </p>
                    
                    <!-- Summary (What Happened) -->
                    <div style="color: #334155; font-size: 14px; line-height: 1.6; font-family: 'Plus Jakarta Sans', Arial, sans-serif; margin-bottom: 16px;">
                        {art['english_summary']}
                    </div>

                    <!-- Strategic Insight Block -->
                    {insight_html}

                    <!-- Q&A & Stance Block -->
                    {qa_html}
                </div>
                """

        # Build Full HTML Wrapper
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AIFOD Korea & Japan AI News</title>
            <style>
                @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
                body {{
                    margin: 0;
                    padding: 0;
                    background-color: #f8fafc;
                    -webkit-text-size-adjust: 100%;
                    -ms-text-size-adjust: 100%;
                }}
            </style>
        </head>
        <body style="font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; padding: 20px 10px;">
            <div style="max-width: 650px; margin: 0 auto; background-color: #f8fafc; text-align: center;">
                
                <!-- Premium Header -->
                <div style="background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 50%, #8b5cf6 100%); border-radius: 16px 16px 0 0; padding: 40px 30px; text-align: center;">
                    <div style="color: #93c5fd; font-size: 12px; font-weight: 700; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 8px;">AIFOD Daily Digest</div>
                    <h1 style="color: #ffffff; margin: 0 0 10px 0; font-size: 28px; font-weight: 800; font-family: 'Plus Jakarta Sans', Arial, sans-serif; letter-spacing: -0.025em;">Korea & Japan AI News</h1>
                    <p style="color: #e0f2fe; margin: 0; font-size: 14px; font-weight: 400; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">
                        Selected and summarized for international development relevance.
                    </p>
                </div>
                
                <!-- Mini Stats Dashboard -->
                <div style="background-color: #ffffff; border-radius: 0 0 16px 16px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.02); border-bottom: 1px solid #e2e8f0; border-left: 1px solid #e2e8f0; border-right: 1px solid #e2e8f0; margin-bottom: 24px;">
                    <table style="width: 100%; border-collapse: collapse; text-align: center;">
                        <tr>
                            <td style="width: 33.33%; border-right: 1px solid #e2e8f0; padding: 5px 0;">
                                <div style="font-size: 20px; font-weight: 800; color: #1e293b;">{total_fetched}</div>
                                <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em; margin-top: 4px;">Evaluated</div>
                            </td>
                            <td style="width: 33.33%; border-right: 1px solid #e2e8f0; padding: 5px 0;">
                                <div style="font-size: 20px; font-weight: 800; color: #8b5cf6;">{len(relevant_articles)}</div>
                                <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em; margin-top: 4px;">Relevant</div>
                            </td>
                            <td style="width: 33.33%; padding: 5px 0;">
                                <div style="font-size: 14px; font-weight: 700; color: #64748b; margin-top: 4px;">{date_str}</div>
                                <div style="font-size: 11px; color: #64748b; text-transform: uppercase; font-weight: 600; letter-spacing: 0.05em; margin-top: 4px;">Report Date</div>
                            </td>
                        </tr>
                    </table>
                    
                    <!-- Country Breakdowns if any relevant -->
                    {f'<div style="margin-top: 15px; font-size: 12px; color: #64748b; font-weight: 500;">Korea: {kr_count} articles &bull; Japan: {jp_count} articles</div>' if relevant_articles else ''}
                </div>
                
                <!-- Main News Section -->
                <div style="margin-bottom: 30px;">
                    {articles_html}
                </div>
                
                <!-- Footer Section -->
                <div style="background-color: #0f172a; border-radius: 16px; padding: 30px; text-align: center;">
                    <p style="color: #94a3b8; font-size: 12px; margin: 0 0 10px 0; font-family: 'Plus Jakarta Sans', Arial, sans-serif; line-height: 1.5;">
                        This digest is compiled daily at midnight (JST/KST) by the AIFOD Aggregator Service.<br>
                        Powered by Google News RSS & Google Gemini API.
                    </p>
                    <p style="color: #64748b; font-size: 11px; margin: 0; font-family: 'Plus Jakarta Sans', Arial, sans-serif;">
                        Prepared exclusively for Henry Hyunwoo Kim (<a href="mailto:{RECIPIENT_EMAIL}" style="color: #93c5fd; text-decoration: none;">{RECIPIENT_EMAIL}</a>)
                    </p>
                </div>
                
            </div>
        </body>
        </html>
        """
        return html_content

    def send_digest_email(self, relevant_articles, total_fetched, date_str):
        """
        Builds the HTML and sends it as a Gmail email.
        """
        try:
            # Generate HTML body
            html_body = self.build_html_digest(relevant_articles, total_fetched, date_str)
            
            # Create email message
            message = MIMEMultipart('alternative')
            
            subject_date = date_str
            status_tag = f"[{len(relevant_articles)} Articles]" if relevant_articles else "[No News]"
            
            message['Subject'] = f"{status_tag} Daily AI News Digest: Korea & Japan - {subject_date}"
            message['To'] = RECIPIENT_EMAIL
            
            # Plain text fallback
            plain_text = f"Daily AI News Digest: Korea & Japan - {subject_date}\n\n"
            plain_text += f"Total Evaluated: {total_fetched}\n"
            plain_text += f"Relevant Articles: {len(relevant_articles)}\n\n"
            for art in relevant_articles:
                plain_text += f"- {art['english_title']} ({art['country']})\n"
                plain_text += f"  Source: {art['source']} | Link: {art['link']}\n"
                plain_text += f"  Summary: {art['english_summary']}\n"
                if art.get('aifod_insight'):
                    plain_text += f"  Strategic Insight: {art['aifod_insight']}\n"
                if art.get('aifod_question'):
                    plain_text += f"  Question: {art['aifod_question']}\n"
                    plain_text += f"  Stance: {art.get('aifod_suggested_answer', '')}\n"
                plain_text += "\n"
            plain_text += "\nCompiled by AIFOD Daily News Bot."
            
            message.attach(MIMEText(plain_text, 'plain'))
            message.attach(MIMEText(html_body, 'html'))
            
            # Encode raw email
            raw_email = base64.urlsafe_b64encode(message.as_bytes()).decode()
            body = {'raw': raw_email}
            
            # Send via Gmail API
            result = self.service.users().messages().send(userId='me', body=body).execute()
            print(f"Daily news digest email sent successfully! Message Id: {result['id']}")
            return result
        except HttpError as error:
            print(f"An error occurred sending the news digest email: {error}")
            raise error

if __name__ == "__main__":
    # Test building and sending (Requires env setup)
    import sys
    try:
        sender = EmailSender()
        # Mock article
        test_articles = [{
            "original_title": "AI 개발도상국을 위한 공헌 프로그램 출범",
            "english_title": "Launch of Contribution Program for AI in Developing Countries",
            "english_summary": "A new AI initiative was announced by Korean agencies to support digital infrastructure in developing countries, providing technical education and subsidized cloud resources.",
            "aifod_insight": "This initiative provides direct capacity-building pathways for Global South partners to leverage Korean infrastructure without proprietary vendor lock-in.",
            "aifod_question": "How can partner countries ensure sustainable funding after the initial bilateral subsidy expires?",
            "aifod_suggested_answer": "Establish local co-investment frameworks and train in-country technicians to transition maintenance locally.",
            "link": "https://example.com/test-news",
            "source": "ICT News Korea",
            "country": "KR",
            "published": datetime.now().isoformat()
        }]
        print("Sending test digest...")
        sender.send_digest_email(test_articles, total_fetched=1, date_str=datetime.now().strftime("%Y-%m-%d"))
    except Exception as e:
        print(f"Test run failed: {e}")
        sys.exit(1)
