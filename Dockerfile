# Base image
FROM ubuntu:22.04

# Working directory, Streamlit does not work at root
WORKDIR /app

# Copy the dependencies file to the working directory
COPY requirements.txt /app/

# Install Python
RUN apt update -y
RUN apt install -y python3-pip python-dev-is-python3 build-essential

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Clear pip cache
RUN rm -rf /root/.cache/pip

RUN apt-get update && apt-get install -y vim

# Copy the current code to the image
COPY . .

EXPOSE 80

# Set environment variables to retrieve the build time as an environment variable
# docker build --build-arg BUILD_TIME="$(date '+%d/%m/%Y %Hh%M')" -t plidockerregistry.azurecr.io/rai .
ARG BUILD_TIME
ENV BUILD_TIME=${BUILD_TIME}

# Run with Streamlit
CMD [ "streamlit", "run", "streamlit_ui_main.py", "--server.port=80", "--server.address=0.0.0.0", "--server.enableWebsocketCompression=false" ]
