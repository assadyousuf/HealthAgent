# Hosted Number You Can Call
1 (855) 972 9720 

Note: This is a twillio free account with limited amount of calls. If you run into any issues let me know and I can check in on it

# Health Agent

This project is a FastAPI-based voice agent that integrates with Twilio to handle WebSocket connections and provide real-time communication for patient intake.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configure Twilio URLs](#configure-twilio-urls)
- [Running the Application](#running-the-application)
- [Usage](#usage)

## Features

- **FastAPI**: A modern, fast (high-performance), web framework for building APIs with Python 3.10+.
- **WebSocket Support**: Real-time communication using WebSockets.
- **CORS Middleware**: Allowing cross-origin requests for testing.
- **Dockerized**: Easily deployable using Docker.
- **Patient Intake**: Collects patient information including demographics, insurance, medical history, and reason for visit.

## Requirements

- Python 3.10
- Docker (for containerized deployment)
- ngrok (for tunneling)
- Twilio Account
- OpenAI API Key
- Deepgram API Key
- Cartesia API Key

## Installation

1. **Set up a virtual environment** (optional but recommended):

   ```sh
   python3 -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

2. **Install dependencies**:

   ```sh
   pip install -r requirements.txt
   ```

3. **Create .env**:
   Copy the example environment file and update with your API keys and Twilio credentials:

   ```sh
   cp env.example .env
   ```

4. **Install ngrok**:
   Follow the instructions on the [ngrok website](https://ngrok.com/download) to download and install ngrok.

## Configure Twilio URLs

1. **Start ngrok**:
   In a new terminal, start ngrok to tunnel the local server:

   ```sh
   ngrok http 8765
   ```

2. **Update the Twilio Webhook**:

   - Go to your Twilio phone number's configuration page
   - Under "Voice Configuration", in the "A call comes in" section:
     - Select "Webhook" from the dropdown
     - Enter your ngrok URL (e.g., http://<your_ngrok_subdomain>.ngrok.io)
     - Ensure "HTTP POST" is selected
   - Click Save at the bottom of the page

3. **Configure streams.xml**:
   - Copy the template file to create your local version:
     ```sh
     cp templates/streams.xml.template templates/streams.xml
     ```
   - In `templates/streams.xml`, replace `<your server url>` with your ngrok URL (e.g., `abc123xyz.ngrok.io` - do not include `http://` or `https://`)
   - The final URL should look like: `wss://abc123xyz.ngrok.io/ws`

## Running the Application

Choose one of these two methods to run the application:

### Using Python (Option 1)

**Run the FastAPI application**:

```sh
# Make sure you're in the HealthAgent directory and your virtual environment is activated
python src/server.py
```

### Using Docker (Option 2)

1. **Build the Docker image**:

   ```sh
   docker build -t health-agent .
   ```

2. **Run the Docker container**:
   ```sh
   docker run -it --rm -p 8765:8765 --env-file .env health-agent
   ```

The server will start on port 8765. Keep this running while you test with Twilio.

## Usage

To start a call, simply make a call to your configured Twilio phone number. The webhook URL will direct the call to your FastAPI application, which will handle it accordingly.

The agent will guide the user through collecting:
- Name and Date of Birth
- Insurance Information (Payer Name and ID)
- Referral Information (if any, and to which physician)
- Chief Medical Complaint
- Address (with validation)
- Contact Information (Phone Number and optional Email)
- Offer available providers and times (mock data)

## Testing

It is also possible to automatically test the server without making phone calls by using a software client. The `twilio-chatbot` example contains a `client.py` that can be adapted for this purpose if needed.

First, update `templates/streams.xml` to point to your server's websocket endpoint. For example:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="ws://localhost:8765/ws"></Stream>
  </Connect>
  <Pause length="40"/>
</Response>
```

Then, start the server with `-t` to indicate we are testing:

```sh
# Make sure you're in the AssortHealthAgent directory and your virtual environment is activated
python src/server.py -t
```

(If you adapt the `client.py` from the `twilio-chatbot` example, you would run it similarly to how it's described in that project's README.) 
