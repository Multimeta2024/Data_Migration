# config/constants.py

CURRENCY = "INR"

# Tally Reserved Group  →  Zoho Account Type
TALLY_RESERVED_TO_ZOHO = {
    # Capital / Equity
    "Capital Account":              "Equity",
    "Reserves & Surplus":           "Equity",
    "Reserves and Surplus":         "Equity",

    # Current Liabilities
    "Current Liabilities":          "Other Current Liability",
    "Duties & Taxes":               "Other Current Liability",
    "Duties and Taxes":             "Other Current Liability",
    "Provisions":                   "Other Current Liability",
    "Sundry Creditors":             "Accounts Payable",

    # Extra user-defined groups rooted at Primary (no reserved ancestor)
    "Other Current Liabilities":    "Other Current Liability",
    "Other Long Term Liabilities":  "Non Current Liability",
    "Salary Payable":               "Other Current Liability",
    "TDS Payable":                  "Other Current Liability",
    "Sales Advance":                "Other Current Liability",
    "Long-Term Investments":        "Other Asset",
    "Software Development -AEP":    "Expense",
    "Research & Development":       "Expense",
    "Vadugapatti Expenses":         "Expense",
    "Farm Connect Shop":            "Expense",

    # Loans / Long-term Liabilities
    "Loans (Liability)":            "Non Current Liability",
    "Secured Loans":                "Non Current Liability",
    "Unsecured Loans":              "Other Liability",
    "Bank OD A/c":                  "Credit Card",

    # Equity / Branch
    "Branch / Divisions":           "Other Asset",

    # Fixed / Non-current Assets
    "Fixed Assets":                 "Fixed Asset",
    "Investments":                  "Other Asset",
    "Misc. Expenses (ASSET)":       "Intangible Asset",
    "Misc Expenses (ASSET)":        "Intangible Asset",

    # Current Assets
    "Current Assets":               "Other Current Asset",
    "Deposits (Asset)":             "Other Current Asset",
    "Loans & Advances (Asset)":     "Other Current Asset",
    "Loans and Advances (Asset)":   "Other Current Asset",
    "Stock-in-hand":                "Stock",
    "Stock in Hand":                "Stock",
    "Stock-in-Hand":                "Stock",      # alias returned by Tally reserved_name
    "Sundry Debtors":               "Accounts Receivable",
    "Bank Accounts":                "Bank",
    "Bank Account":                 "Bank",
    "Cash-in-hand":                 "Cash",
    "Cash in Hand":                 "Cash",
    "Cash-in-Hand":                 "Cash",       # alias returned by Tally reserved_name

    # Suspense
    "Suspense A/c":                 "Other Current Asset",
    "Suspense":                     "Other Current Asset",

    # Income
    "Sales Accounts":               "Income",
    "Direct Incomes":               "Income",
    "Indirect Incomes":             "Other Income",
    "Other Income":                 "Other Income",

    # Expenses
    "Purchase Accounts":            "Cost of Goods Sold",
    "Direct Expenses":              "Cost of Goods Sold",
    "Indirect Expenses":            "Expense",
}

# Zoho account types that CANNOT have sub-accounts (Zoho restriction)
NO_SUBACCOUNT_TYPES = {
    "Bank", "Accounts Receivable", "Accounts Payable",
    "Payment Clearing Account", "Credit Card", "Overseas Tax Payable",
    "Deferred Tax Asset", "Deferred Tax Liability",
}

# Normal balance side for Debit/Credit determination
DEBIT_NORMAL = {
    "Other Current Asset", "Fixed Asset", "Other Asset", "Cash", "Bank",
    "Stock", "Accounts Receivable", "Intangible Asset", "Non Current Asset",
    "Deferred Tax Asset",
    "Cost of Goods Sold", "Expense", "Other Expense",
}
CREDIT_NORMAL = {
    "Other Current Liability", "Credit Card", "Non Current Liability",
    "Other Liability", "Accounts Payable", "Overseas Tax Payable",
    "Deferred Tax Liability", "Equity",
    "Income", "Other Income",
}

# Zoho-predefined system accounts that we must exclude from COA to prevent duplication error
ZOHO_SYSTEM_ACCOUNTS = {
    "other expenses", "petty cash", "advance tax", "discount", "shipping charge",
    "sales", "interest income", "cost of goods sold",
    "travel expense", "travel expenses",
    "advertising and marketing", "advertising & marketing",
    "automobile expense", "bad debt", "bank fees and charges",
    "consulting expense", "depreciation expense",
    "it and internet expenses", "it & internet expenses",
    "janitorial expense", "meals and entertainment",
    "office supplies", "postage", "printing and stationery",
    "rent expense", "repairs and maintenance",
    "salaries and employee wages", "telephone expense",
    "uncategorized", "ask my accountant", "reconciliation discrepancies",
    "retained earnings", "opening balance adjustments", "exchange gain or loss",
    "unearned revenue", "undeposited funds", "drawings", "purchase discount",
    "general expense", "general expenses", "insurance expense", "legal expense"
}

# Mapping common variations/pluralizations to exact Zoho pre-defined system account names
ZOHO_SYSTEM_CANONICAL = {
    "travel expense": "Travel Expense",
    "travel expenses": "Travel Expense",
    "other expense": "Other Expenses",
    "other expenses": "Other Expenses",
    "general expense": "Other Expenses",
    "general expenses": "Other Expenses",
    "advertising & marketing": "Advertising and Marketing",
    "advertising and marketing": "Advertising and Marketing",
    "automobile expense": "Automobile Expense",
    "bad debt": "Bad Debt",
    "bank fees and charges": "Bank Fees and Charges",
    "consulting expense": "Consulting Expense",
    "depreciation expense": "Depreciation Expense",
    "it & internet expenses": "IT and Internet Expenses",
    "it and internet expenses": "IT and Internet Expenses",
    "janitorial expense": "Janitorial Expense",
    "meals and entertainment": "Meals and Entertainment",
    "office supplies": "Office Supplies",
    "postage": "Postage",
    "printing & stationery": "Printing and Stationery",
    "printing and stationery": "Printing and Stationery",
    "rent expense": "Rent Expense",
    "repairs and maintenance": "Repairs and Maintenance",
    "salaries and employee wages": "Salaries and Employee Wages",
    "telephone expense": "Telephone Expense",
    "cost of goods sold": "Cost of Goods Sold",
    "sales": "Sales",
    "discount": "Discount",
    "petty cash": "Petty Cash",
}


# Zoho-restricted types whose opening balances must NOT be imported via COA CSV
ZOHO_NO_OB_TYPES = {"Accounts Receivable", "Accounts Payable", "Bank", "Credit Card"}

# GST state code → full state name
GST_STATE_MAP = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar",
    "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand",
    "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "28": "Andhra Pradesh", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry", "35": "Andaman and Nicobar Islands",
    "36": "Telangana", "37": "Andhra Pradesh (New)", "38": "Ladakh"
}

# State name/GST prefix → standard 2-letter state code
STATE_TO_CODE = {
    "01": "JK", "02": "HP", "03": "PB", "04": "CH", "05": "UK",
    "06": "HR", "07": "DL", "08": "RJ", "09": "UP", "10": "BR",
    "11": "SK", "12": "AR", "13": "NL", "14": "MN", "15": "MZ",
    "16": "TR", "17": "ML", "18": "AS", "19": "WB", "20": "JH",
    "21": "OD", "22": "CG", "23": "MP", "24": "GJ", "26": "DN",
    "27": "MH", "28": "AD", "29": "KA", "30": "GA", "31": "LD",
    "32": "KL", "33": "TN", "34": "PY", "35": "AN", "36": "TS",
    "37": "AD", "38": "LA",
    "jammu and kashmir": "JK", "jammu & kashmir": "JK", "himachal pradesh": "HP",
    "punjab": "PB", "chandigarh": "CH", "uttarakhand": "UK", "uttaranchal": "UK",
    "haryana": "HR", "delhi": "DL", "rajasthan": "RJ", "uttar pradesh": "UP",
    "bihar": "BR", "sikkim": "SK", "arunachal pradesh": "AR", "nagaland": "NL",
    "manipur": "MN", "mizoram": "MZ", "tripura": "TR", "meghalaya": "ML",
    "assam": "AS", "west bengal": "WB", "jharkhand": "JH", "odisha": "OD",
    "orissa": "OD", "chhattisgarh": "CG", "madhya pradesh": "MP", "gujarat": "GJ",
    "dadra and nagar haveli and daman and diu": "DN", "dadra & nagar haveli & daman & diu": "DN",
    "daman and diu": "DD", "daman & diu": "DD", "maharashtra": "MH", "andhra pradesh": "AD",
    "karnataka": "KA", "goa": "GA", "lakshadweep": "LD", "kerala": "KL",
    "tamil nadu": "TN", "tamilnadu": "TN", "puducherry": "PY", "pondicherry": "PY",
    "andaman and nicobar islands": "AN", "andaman & nicobar islands": "AN",
    "telangana": "TS", "andhra pradesh (new)": "AD", "ladakh": "LA"
}

# ---------------------------------------------------------------------------
# CSV Column Headers
# ---------------------------------------------------------------------------
COA_HEADERS = [
    "Account Name", "Account Code", "Description", "Account Type",
    "Parent Account", "Account #", "Currency", "Opening Balance", "Debit or Credit"
]

OB_HEADERS = [
    "Migration Date", "Account Name", "Debit or Credit",
    "Currency Code", "Amount", "Exchange Rate", "Contact Name"
]

CUST_HEADERS = [
    "Display Name", "Customer Number", "Place of Contact", "Currency Code",
    "Company Name", "Salutation", "First Name", "Last Name", "EmailID",
    "Phone", "MobilePhone", "Facebook", "Twitter", "Department", "Designation",
    "Payment Terms", "Payment Terms Label", "Notes", "Website", "Exemption Reason",
    "GST Treatment", "GST Identification Number (GSTIN)", "PAN Number",
    "Billing Address", "Billing City", "Billing State", "Billing Country", "Billing Pin Code",
    "Billing Phone", "Shipping Address", "Shipping City", "Shipping State", "Shipping Country",
    "Shipping Pin Code", "Shipping Phone", "Contact Persons Details", "Attachment IDs",
    "Outstanding Balance", "Debit or Credit of Outstanding Balance", "Payment Terms In Days",
    "Branch Name"
]

VEND_HEADERS = [
    "Display Name", "Vendor Number", "Source Of Supply", "Currency Code",
    "Company Name", "Salutation", "First Name", "Last Name", "EmailID",
    "Phone", "MobilePhone", "Facebook", "Twitter", "Department", "Designation",
    "Payment Terms", "Payment Terms Label", "Notes", "Website", "Exemption Reason",
    "GST Treatment", "GST Identification Number (GSTIN)", "PAN Number",
    "Billing Address", "Billing City", "Billing State", "Billing Country", "Billing Pin Code",
    "Billing Phone", "Shipping Address", "Shipping City", "Shipping State", "Shipping Country",
    "Shipping Pin Code", "Shipping Phone", "Contact Persons Details", "Attachment IDs",
    "Outstanding Balance", "Debit or Credit of Outstanding Balance", "Payment Terms In Days",
    "Branch Name"
]

CUST_ADV_HEADERS = [
    "Payment Number Prefix", "Payment Number Suffix", "Date", "Payment Status",
    "Description of Supply", "Payment Type", "Mode", "Description", "Exchange Rate",
    "Amount", "Deposit To", "Bank Charges", "Reference Number", "Attachment IDs",
    "Template Name", "Customer Name", "Place of Supply", "GST Treatment",
    "GST Identification Number (GSTIN)", "Tax Name", "Tax Percentage", "Tax Type",
    "Tax Account", "Invoice Number", "Invoice Date", "Amount Applied to Invoice",
    "Withholding Tax Amount"
]

VEND_ADV_HEADERS = [
    "Payment Number", "Date", "Vendor Name", "Mode", "Description", "Exchange Rate",
    "Amount", "Paid Through", "Tax Account", "Reference Number", "Bill Number",
    "Bill Amount", "Reverse Charge Tax Rate", "Reverse Charge Tax Type", "Reverse Charge Tax Name",
    "Payment Type", "GST Treatment", "GST Identification Number (GSTIN)", "Destination of Supply",
    "Description of Supply", "TDS Name", "TDS Percentage", "TDS Section Code", "TDS Amount", "Bill Date"
]

INVOICE_HEADERS = [
    "Invoice Number", "Estimate Number", "Invoice Date", "Invoice Status",
    "Customer Name", "GST Treatment", "TCS Tax Name", "TCS Percentage",
    "TCS Amount", "Nature Of Collection", "TCS Payable Account", "TCS Receivable Account",
    "GST Identification Number (GSTIN)", "TDS Name", "TDS Percentage",
    "TDS Section Code", "TDS Amount", "Place of Supply", "PurchaseOrder",
    "Expense Reference ID", "Payment Terms", "Payment Terms Label", "Due Date",
    "Expected Payment Date", "Sales person", "Shipping Charge Tax Name",
    "Shipping Charge Tax Type", "Shipping Charge Tax %", "Shipping Charge",
    "Shipping Charge Tax Exemption Code", "Shipping Charge SAC Code",
    "Currency Code", "Exchange Rate", "Account", "Item Name", "SKU",
    "Item Desc", "Item Type", "HSN/SAC", "Quantity", "Usage unit",
    "Item Price", "Item Tax Exemption Reason", "Is Inclusive Tax", "Item Tax",
    "Item Tax Type", "Item Tax %", "Reverse Charge Tax Name", "Reverse Charge Tax Rate",
    "Reverse Charge Tax Type", "Project Name", "Supply Type", "Discount Type",
    "Is Discount Before Tax", "Entity Discount Percent", "Entity Discount Amount",
    "Discount", "Discount Amount", "Adjustment", "Adjustment Description",
    "E-Commerce Operator Name", "E-Commerce Operator GSTIN", "PayPal", "Razorpay",
    "Partial Payments", "Template Name", "Notes", "Terms & Conditions",
    "Branch Name", "Warehouse Name"
]

CREDIT_NOTE_HEADERS = [
    "Credit Note Number", "Credit Note Date", "Associated Invoice Number", "Reference Invoice Type",
    "Reference#", "Credit Note Status", "Reason", "Customer Name", "GST Treatment",
    "GST Identification Number (GSTIN)", "Place of Supply", "Sales person", "Currency Code",
    "Exchange Rate", "Item Name", "SKU", "Item Desc", "Item Type", "Account", "HSN/SAC",
    "Quantity", "Usage unit", "Item Price", "Item Tax", "Item Tax %", "Item Tax Type",
    "Is Inclusive Tax", "Item Tax Exemption Reason", "Project Name", "Discount Type",
    "Is Discount Before Tax", "Entity Discount Percent", "Entity Discount Amount", "Discount",
    "Discount Amount", "Shipping Charge", "Adjustment", "Adjustment Description", "Template Name",
    "Notes", "Terms & Conditions", "Associated Invoice Date", "Branch", "Subject",
    "Warehouse Name", "Reverse Charge Tax Name", "Reverse Charge Tax Rate", "Reverse Charge Tax Type",
    "Supply Type", "TCS Tax Name", "TCS Percentage", "Nature Of Collection", "TCS Amount",
    "Shipping Charge Tax Name", "Shipping Charge Tax Type", "Shipping Charge Tax %",
    "Shipping Charge SAC Code", "Shipping Charge Tax Exemption Code"
]

VENDOR_CREDIT_HEADERS = [
    "Vendor Credit Date", "Vendor Credit Number", "Vendor Credit Status", "Vendor Name",
    "Reference Bill Type", "Reference#", "Currency Code", "Exchange Rate", "Source of Supply", "Destination of Supply",
    "GST Treatment", "GST Identification Number (GSTIN)", "Is Inclusive Tax", "Account",
    "Item Name", "SKU", "Item Desc", "Item Price", "Quantity", "Usage unit",
    "Item Tax", "Item Tax %", "Item Tax Type", "Item Tax Exemption Reason",
    "Item Tax Exemption Code", "Reverse Charge Tax Name", "Reverse Charge Tax Rate",
    "Reverse Charge Tax Type", "Reverse Charge Tax Amount", "SubTotal", "Total",
    "Balance", "Notes", "Reference Bill#", "Created By", "Last Modified By",
    "Project Name", "Item Type", "Is Discount Before Tax", "Entity Discount Percent",
    "Entity Discount Amount", "Discount", "Discount Amount", "Adjustment",
    "Adjustment Description", "Branch Name", "Warehouse Name", "CF.Item_Accounting",
    "Accounting Code", "HSN/SAC", "ITC Eligibility", "Supply Type"
]

# Zoho Books Bills import CSV headers
BILL_HEADERS = [
    "Bill Number", "Bill Date", "Vendor Name",
    "GST Treatment", "GST Identification Number (GSTIN)", "Place of Supply",
    "PurchaseOrder", "Payment Terms", "Payment Terms Label", "Due Date",
    "Currency Code", "Exchange Rate",
    "Account", "Item Name", "SKU", "Item Desc", "Item Type", "HSN/SAC",
    "Quantity", "Usage unit", "Rate", "Item Price",
    "Is Inclusive Tax", "Tax Name", "Tax Percentage", "Tax Type", "Tax Exemption Reason", "Item Tax", "Item Tax Type", "Item Tax %", "Item Tax Exemption Reason",
    "Branch Name"
]

# Zoho Books Customer Payments import CSV headers
PAYMENT_HEADERS = [
    "Payment Number Prefix", "Payment Number Suffix",
    "Customer Name", "Place of Supply", "GST Treatment",
    "GST Identification Number (GSTIN)", "Payment Type", "Description of Supply",
    "Tax Name", "Tax Percentage", "Tax Type",
    "Date", "Mode", "Exchange Rate", "Amount", "Description",
    "Bank Charges", "Tax Account", "Deposit To", "Reference Number",
    "Invoice Number", "Amount Applied to Invoice", "Invoice Amount",
    "Withholding Tax Amount", "Branch Name"
]

# Zoho Books Vendor Payments import CSV headers
VENDOR_PAYMENT_HEADERS = [
    "Payment Number", "Date", "Vendor Name", "Mode", "Paid Through",
    "Amount", "Exchange Rate", "Reference Number", "Description",
    "Bill Number", "Bill Date", "Amount Applied to Bill",
    "Bank Charges", "Tax Account", "Branch Name"
]

# Zoho Books Items import CSV headers (matches the official template exactly)
ITEM_HEADERS = [
    "Item Name", "SKU", "HSN/SAC", "Description", "Rate", "Product Type",
    "Account", "Usage unit", "Purchase Description", "Purchase Rate",
    "Item Type", "Purchase Account", "Inventory Account", "Reorder Point",
    "Vendor", "Initial Stock", "Initial Stock Rate", "Stock On Hand", "Status",
    "Taxability Type", "Exemption Reason",
    "Inter State Tax Name", "Inter State Tax Type", "Inter State Tax Rate",
    "Intra State Tax Name", "Intra State Tax Type", "Intra State Tax Rate",
    "Warehouse Name", "CF.custom_field"
]

# Zoho Books Item Opening Stock import CSV headers (matches official template)
ITEM_OPENING_STOCK_HEADERS = [
    "Item Name", "SKU", "Opening Stock", "Opening Stock Value",
    "TrackSerialNumber", "Track Batches", "Enable Bin Tracking",
    "Location Name", "Batch Reference#", "Manufacturer Batch#",
    "Manufactured Date", "Expiry Date", "Quantity In",
    "Bin Name", "Bin Quantity", "Serial Numbers"
]

# Tally unit of measure → Zoho unit mapping
TALLY_UNIT_TO_ZOHO = {
    "nos": "pcs", "no": "pcs", "no.": "pcs", "nos.": "pcs",
    "pcs": "pcs", "pc": "pcs", "piece": "pcs", "pieces": "pcs",
    "unit": "pcs", "units": "pcs",
    "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg",
    "gm": "gm", "gms": "gm", "gram": "gm", "grams": "gm", "g": "gm",
    "ltr": "ltr", "ltrs": "ltr", "litre": "ltr", "litres": "ltr", "liter": "ltr",
    "ml": "ml", "mtr": "mtr", "mtrs": "mtr", "meter": "mtr", "meters": "mtr",
    "cm": "cm", "mm": "mm", "ft": "ft", "feet": "ft", "inch": "in", "in": "in",
    "box": "box", "boxes": "box", "set": "set", "sets": "set",
    "doz": "doz", "dozen": "doz", "bag": "bag", "bags": "bag",
    "ton": "ton", "tons": "ton", "mt": "ton",
    "sqft": "sqft", "sqmtr": "sqmtr", "sqm": "sqmtr",
    "pair": "pair", "pairs": "pair", "roll": "roll", "rolls": "roll",
    "sheet": "sheet", "sheets": "sheet", "bottle": "bottle", "bottles": "bottle",
    "pack": "pack", "packs": "pack", "can": "can", "cans": "can",
    "bundle": "bundle", "bundles": "bundle",
}

