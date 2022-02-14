set -e

# python3 -m doctest crypto_robot/*.py
python3 doctest_runner.py
echo "doctest No problem, Sir!✅\n"
