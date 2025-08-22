# Use a general-purpose base image which is good for building dependencies
FROM buildpack-deps:bullseye

# Set the working directory
WORKDIR /usr/src/app

# Install system dependencies, including Python, Node.js, and Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Python
    python3.9 \
    python3-pip \
    # Node.js
    curl \
    gnupg \
    # Chromium and its dependencies for Puppeteer
    chromium \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    wget \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

# Configure Python 3.9 as the default python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.9 1

# Install Node.js v18 (a recent LTS version)
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash -
RUN apt-get install -y nodejs

# Set the Puppeteer executable path so whatsapp-web.js uses the system-installed Chromium
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

# Copy dependency definition files first to leverage Docker's layer caching
COPY requirements.txt ./
COPY package.json ./
# Use wildcard to copy lock file if it exists
COPY package-lock.json* ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies at the project root
RUN npm install --production --legacy-peer-deps

# Copy the rest of the application source code
COPY . .

# Expose the port used by Streamlit
EXPOSE 8501

# The command to run when the container starts
CMD ["streamlit", "run", "start.py", "--server.port=8501", "--server.address=0.0.0.0"] 