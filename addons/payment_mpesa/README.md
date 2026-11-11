# M-Pesa Payment Provider for Odoo

This module integrates M-Pesa (Safaricom Kenya) payment gateway with Odoo's payment system.

## Features

- **STK Push Integration**: Customers receive payment prompts directly on their M-Pesa app
- **Automatic Payment Verification**: Real-time callback handling for payment status
- **Test & Production Mode**: Supports both sandbox and live environments
- **Kenyan Phone Number Support**: Automatic formatting of phone numbers

## Installation

1. Copy the `payment_mpesa` folder to your Odoo addons directory
2. Restart your Odoo server
3. Update the Apps list (Apps → Update Apps List)
4. Search for "M-Pesa" and install the module

## Configuration

### 1. Get M-Pesa API Credentials

You need to register your application on the Safaricom Developer Portal:

**For Sandbox (Testing):**
1. Visit https://developer.safaricom.co.ke/
2. Create an account and login
3. Create a new app and select "Lipa Na M-Pesa Online"
4. Get your:
   - Consumer Key
   - Consumer Secret
   - Business Short Code
   - Passkey

**For Production (Live):**
1. Contact Safaricom to get your production credentials
2. Complete the onboarding process

### 2. Configure in Odoo

1. Go to **Settings → Invoicing → Payment Providers**
2. Find and open **M-Pesa**
3. Fill in the credentials:
   - **State**: Enable for production or Test Mode for sandbox
   - **Consumer Key**: Your M-Pesa app consumer key
   - **Consumer Secret**: Your M-Pesa app consumer secret
   - **Account Type**: Paybill, or Till Number (Buy Goods)
   - **Business Shortcode**: Your Paybill number, or for a Till the store (head office)
     number the passkey was issued for
   - **Till Number**: (Till only) the till that receives the money, if different
   - **Passkey**: Your M-Pesa online passkey
   - **Callback URL**: must be public **https**, e.g.
     `https://lashesbyshazz.com/payment/stk/callback`. Daraja does not call http
     or raw IP addresses, and rejects URLs containing "mpesa" or "safaricom".
4. **Save** and **Publish** the payment provider

### Switching from PesaPal to M-Pesa

1. `-u payment_mpesa` (links the payment method, the checkout phone field and the
   accounting payment method; does not switch anything on or off)
2. Fill in the M-Pesa credentials above, set **State** to Enabled, then Publish
3. On the PesaPal provider, Unpublish it (or set State to Disabled)

M-Pesa then appears at the eCommerce checkout, on portal invoices and on the
appointment payment page. A paid order is confirmed and invoiced the same way it
was with PesaPal.

### How a payment completes

The customer enters their number, gets the STK prompt and enters their PIN while
the page waits. Safaricom's callback marks the payment done. If the callback never
arrives, the "M-Pesa: check pending payments" cron asks Daraja for the result
every 2 minutes (STK Query), so payments do not stay stuck as pending.

### 3. Test the Integration

1. Go to your appointment booking or checkout page
2. Select M-Pesa as the payment method
3. Enter your M-Pesa registered phone number (254XXXXXXXXX format)
4. Click "Pay"
5. Check your phone for the STK Push prompt
6. Enter your M-Pesa PIN to complete the payment

## Phone Number Format

The module accepts phone numbers in the following formats:
- `254712345678` (preferred)
- `0712345678` (auto-converted to 254 format)
- `+254712345678` (auto-converted)
- `712345678` (auto-converted)

## Troubleshooting

### STK Push Not Received

- Verify your phone number is registered with M-Pesa
- Check that the Business Shortcode in settings matches your M-Pesa account
- Ensure you're using Test Mode with sandbox credentials for testing

### Payment Not Confirming

- Check Odoo logs for callback errors
- Verify your Callback URL is accessible from the internet (use ngrok for local testing)
- Ensure your credentials are correct

### API Authentication Errors

- Verify Consumer Key and Consumer Secret are correct
- Check if your M-Pesa app is active on the developer portal
- Ensure you're using the correct mode (Test vs Production)

## Support

For issues related to:
- **M-Pesa API**: Contact Safaricom support or check https://developer.safaricom.co.ke/
- **Odoo Integration**: Create an issue in the repository or contact support

## License

LGPL-3
