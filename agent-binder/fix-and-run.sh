#!/bin/bash
# Fix "Cannot find module './xxx.js'" and other build issues
set -e
cd "$(dirname "$0")"

echo "Cleaning build artifacts..."
rm -rf .next
rm -rf node_modules/.cache

echo "Ensuring dependencies are installed..."
if [ ! -d "node_modules" ]; then
  npm install
fi

echo "Building..."
npm run build

echo "Done. Run 'npm run dev' for development or 'npm run start' for production."
