# Example invocation. Run from inside scripts/ (python -m resolves the module
# from the current directory). --out_dir must already exist. See scripts/README.md.
python -m generate_user_sessions_file \
    --country "Lebanon" \
    --annotator_id 0 \
    --batch_sizes "[32, 32, -1]" \
    --out_dir "./test_user_sessions"

# python -m generate_user_sessions_file --report