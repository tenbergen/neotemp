#!/bin/bash

if [ $EUID > 0 ]
   then echo "Please run with sudo. Exiting."
   exit
fi

echo "Updating system and installing required software..."
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y python3-pip
echo "   done."

echo "Installing required modules..."
sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel astral
echo "   done."

echo "Setting up neotemp service..."
sudo cp neotemp.service /etc/systemd/system/neotemp.service
sudo systemctl enable neotemp.service
echo "   done."

echo "Starting neotemp..."
sudo systemctl start neotemp.service
echo "   installation complete."
