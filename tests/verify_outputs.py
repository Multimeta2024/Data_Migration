import csv

# Check COA - should have blank Opening Balance and Debit or Credit
with open('outputs/tally_dumps/zoho_coa_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

has_ob = any(r.get('Opening Balance', '').strip() for r in rows)
has_dc = any(r.get('Debit or Credit', '').strip() for r in rows)
print(f'COA rows: {len(rows)}')
print(f'COA has any Opening Balance values: {has_ob}  (should be False)')
print(f'COA has any Debit or Credit values: {has_dc}  (should be False)')

# Check OB - should have 0 AR and AP entries when importing via open invoices/bills
with open('outputs/tally_dumps/zoho_opening_balances_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    ob_rows = list(reader)

ar_ap = [r for r in ob_rows if r.get('Account Name', '') in ('Accounts Receivable', 'Accounts Payable')]
unearned_prepaid = [r for r in ob_rows if r.get('Account Name', '') in ('Unearned Revenue', 'Prepaid Expenses')]
print(f'\nOB CSV rows: {len(ob_rows)}')
print(f'OB CSV AR/AP normal entries: {len(ar_ap)}  (should be 0 when AR/AP imported via invoices/bills)')
print(f'OB CSV Unearned/Prepaid entries: {len(unearned_prepaid)}  (should be 0)')

# Check Customers/Vendors - should have NO opening balances (blank)
with open('outputs/tally_dumps/zoho_customers_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    cust_rows = list(reader)
has_cust_ob = any(r.get('Opening Balance', '').strip() for r in cust_rows)
print(f'\nCustomer Master rows: {len(cust_rows)}')
print(f'Customer Master has any Opening Balance: {has_cust_ob}  (should be False)')

with open('outputs/tally_dumps/zoho_vendors_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    vend_rows = list(reader)
has_vend_ob = any(r.get('Opening Balance', '').strip() for r in vend_rows)
print(f'Vendor Master rows: {len(vend_rows)}')
print(f'Vendor Master has any Opening Balance: {has_vend_ob}  (should be False)')

# Check Customer Advances CSV
with open('outputs/tally_dumps/zoho_customer_advances_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    cust_adv_rows = list(reader)
print(f'\nCustomer Advances CSV rows: {len(cust_adv_rows)}')

# Check Vendor Advances CSV
with open('outputs/tally_dumps/zoho_vendor_advances_import.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    vend_adv_rows = list(reader)
print(f'Vendor Advances CSV rows: {len(vend_adv_rows)}')

print('\nFirst 5 OB rows:')
for r in ob_rows[:5]:
    acct = r['Account Name']
    dc = r['Debit or Credit']
    amt = r['Amount']
    contact = r['Contact Name']
    print(f'  {acct} | {dc} | {amt} | Contact: {contact}')
