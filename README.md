# Mertik Maxitrol Fireplace Integration for Home Assistant

Welcome to the Mertik Maxitrol Fireplace Integration for Home Assistant, an innovative solution designed to seamlessly integrate your fireplace into your smart home ecosystem. This custom component allows you to control and monitor your fireplace directly from Home Assistant, enhancing your home's comfort and convenience. 

## **Compatibility**

This integration is designed to be compatible with fireplaces that utilize the Mertik Maxitrol WiFi modules

| Part No.     	| Compatible? 	| Auto discovery?* 	|
|--------------	|-------------	|------------------	|
| B6R-WME      	| Yes         	| Yes              	|
| B6R-W2BE-0   	| Yes         	| Yes              	|
| B6R-WWN 	    | Yes         	| No / Not sure    	|

Fireplaces using these modules are usually controllable via the following iOS/Android applications:

- MyFire
- Trimline Fires
- RAISfire
- Gazco MyFire
- Thermocet International
- Fire Connects
- ITALKERO Fires
- Signi Fires
- SAFIRE
- attika Fire
- Ortal Heating Solutions


## **Requirements**

- A compatible fireplace equipped with a Mertik Maxitrol wifi module that is connected to your local Wi-Fi network.

## **Installation Guide**

### **Method 1: Manual Installation**
1. **Download Files**: Clone or download the `custom_components` folder from this repository.
2. **Copy to Home Assistant**: Transfer the downloaded files to your Home Assistant's `custom_components` directory.
3. **Restart Home Assistant**: Ensure the new integration is recognized by restarting Home Assistant.

### **Method 2: HACS (Home Assistant Community Store)**
1. **Add Repository**: In HACS, navigate to "Integrations" then click on the "+ Explore & Add Integrations" button. Use the URL of this GitHub repository to add it as a custom repository.
2. **Install Integration**: Search for "Mertik Maxitrol Fireplace Integration" and click "Install".

### **Configuration**
After installation by either method, proceed to configure the integration:
1. Navigate to **Configuration > Integrations** in Home Assistant.
2. Click the **+ Add Integration** button and search for **Mertik Maxitrol**.
3. Select the integration and Home Assistant will automatically search your local network for the module, adding the entities to your system. If auto discovery is not working for you, figure out the IP (look in the WLAN client list on your Internet Router) and fill it in manually.

## **Disclaimer**

Please use this integration at your own risk. The developers take no responsibility for any issues that may arise from the use of this software.
