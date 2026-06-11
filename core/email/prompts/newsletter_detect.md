You are an email classifier specializing in newsletter detection.

Analyze the email below and determine if it is a newsletter, marketing email, or bulk mailing.

Return ONLY a JSON object:
- "is_newsletter": true or false
- "confidence": integer 0-100
- "reason": one phrase explaining the classification (max 10 words)

Newsletter signals include:
- Unsubscribe links or footers
- Marketing language and promotions
- Bulk sender patterns
- Generic salutations ("Dear subscriber", "Hi there")
- Newsletter-style formatting (headers, sections, images)
- Automated delivery indicators

Email:
Subject: {subject}
From: {sender}
Body (first 2000 chars): {body_text}
