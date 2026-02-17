from flask import Flask, request, jsonify, send_file, render_template, send_from_directory
from flask_cors import CORS
import os
import requests
from groq import Groq
import tempfile
import uuid
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure your API keys here - REPLACE WITH YOUR ACTUAL KEYS
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ELEVENLABS_API_KEY = os.getenv('ELEVENLABS_API_KEY')
ELEVENLABS_VOICE_ID = "xctasy8XvGp2cVO9HL9k"

# Initialize Groq client
groq_client = Groq(api_key=GROQ_API_KEY)

# Store conversation history (in production, use a database)
conversations = {}

def get_therapist_prompt():
    return """You are a compassionate, professional AI therapist. Your role is to:
    - Listen actively and empathetically
    - Ask thoughtful, open-ended questions
    - Provide supportive and non-judgmental responses
    - Help users explore their thoughts and feelings
    - Offer coping strategies when appropriate
    - Maintain professional boundaries
    - Always remind users that you're an AI and suggest professional help for serious concerns
    - Do not give too long replies. it should range between 10 to 30 words. 
    
    Keep responses concise but warm, typically 2-4 sentences. Focus on understanding and supporting the user."""

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get('message', '')
        session_id = data.get('session_id', str(uuid.uuid4()))
        
        # Initialize conversation history if new session
        if session_id not in conversations:
            conversations[session_id] = [
                {"role": "system", "content": get_therapist_prompt()}
            ]
        
        # Add user message to conversation
        conversations[session_id].append({"role": "user", "content": user_message})
        
        # Get response from Groq
        chat_completion = groq_client.chat.completions.create(
            messages=conversations[session_id],
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=300
        )
        
        ai_response = chat_completion.choices[0].message.content
        
        # Add AI response to conversation history
        conversations[session_id].append({"role": "assistant", "content": ai_response})
        
        # Keep conversation history manageable (last 20 messages)
        if len(conversations[session_id]) > 21:  # system + 20 messages
            conversations[session_id] = [conversations[session_id][0]] + conversations[session_id][-20:]
        
        return jsonify({
            'response': ai_response,
            'session_id': session_id
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/text-to-speech', methods=['POST'])
def text_to_speech():
    try:
        data = request.json
        text = data.get('text', '')
        
        # Check if API key is configured
        if ELEVENLABS_API_KEY == "your_elevenlabs_api_key_here" or not ELEVENLABS_API_KEY:
            return jsonify({'error': 'ElevenLabs API key not configured'}), 400
        
        # ElevenLabs API endpoint
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": ELEVENLABS_API_KEY
        }
        
        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.5
            }
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            # Create temporary file to store audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_file.write(response.content)
            temp_file.close()
            
            return send_file(temp_file.name, as_attachment=True, download_name='speech.mp3', mimetype='audio/mpeg')
        else:
            return jsonify({'error': f'ElevenLabs API error: {response.status_code} - {response.text}'}), 500
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return send_file('index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('.', filename)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    # Check if running locally or remotely
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--https':
        # For mobile access with HTTPS: python app.py --https
        # Install pyOpenSSL first: pip install pyOpenSSL
        app.run(debug=True, host='0.0.0.0', port=5000, ssl_context='adhoc')
    else:
        # For local development with HTTP: python app.py
        app.run(debug=True, host='0.0.0.0', port=5000)