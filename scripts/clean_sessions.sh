#!/bin/bash

# Clean up local session logs and pipes
SESSION_DIR=".treecode/sessions"

if [ -d "$SESSION_DIR" ]; then
    echo "Cleaning up $SESSION_DIR..."
    rm -rf "$SESSION_DIR"/*
    echo "Done."
else
    echo "No sessions to clean."
fi
