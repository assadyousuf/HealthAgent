# Use an official Python runtime as a parent image
FROM python:3.10-bullseye

# Set the working directory in the container
WORKDIR /AssortHealthAgent

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the src directory contents into the container
COPY src/ .

# Expose the desired port
EXPOSE 8765

# Run the application
CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8765"] 