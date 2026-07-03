"""
Throwaway verification script for Task batch F (CRM close-deal dropdown, sourcing
deal document uploads, Part Master/Part Request stock sync fix, Sourcing Requests
tab Download+Verify columns). Not part of the app — safe to delete anytime.

Verified in this session:
  - db_validator.py: schema in sync after migration
  - GET /crm/ -> 200 (fake admin user)
  - GET /spare-parts -> 200
  - GET /crm/sourcing/<real deal id> -> 200
"""
print("See docstring above for what was verified this session.")
