python -m generate_user_sessions_file \
    --country "Lebanon" \
    --annotator_id 0 \
    --batch_sizes "[32, 32, -1]" \
    --out_dir "./test_user_sessions"

# python -m generate_user_sessions_file --report