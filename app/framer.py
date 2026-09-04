import os
import json
import logging
import traceback
from openai import OpenAI
from app.db import supabase

logger = logging.getLogger(__name__)
openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Removed framing functions (generate_tier_summary, generate_comparison_summary, run_framing_job, generate_single_cluster_framing)
# per Bridge Chambers ruling. Do not reintroduce per-tier comparison shape.
