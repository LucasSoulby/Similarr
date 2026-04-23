# Use a lightweight, official Python image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your actual script and config
COPY discovery.py .
COPY config.json .

# NEW: Copy the templates folder so Flask can find the HTML
COPY templates/ ./templates/

# Tell the container to run your script when it starts
CMD ["python", "-u", "discovery.py"]