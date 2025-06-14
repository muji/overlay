#!/bin/bash

# Set the upload path
UPLOAD_DIR="/var/www/html/public/assets/uploads"

# Create the folder if it doesn't exist
mkdir -p "$UPLOAD_DIR"

# Change ownership to your user (replace 'ali' with your actual username if needed)
chown -R ali:ali "$UPLOAD_DIR"

# Give write permissions to the owner and group
chmod -R 775 "$UPLOAD_DIR"

# Optional: Log output
echo "✅ Upload folder permission fixed for $UPLOAD_DIR"
