import sys
from pathlib import Path
import yt_dlp


def download_audio(url):
    # Directory containing this Python script
    script_dir = Path(__file__).resolve().parent

    # Create ./unprocessed next to the script
    output_dir = script_dir / "unprocessed"
    output_dir.mkdir(parents=True, exist_ok=True)

    options = {
        "format": "bestaudio/best",

        # Save downloaded/converted file in ./unprocessed/
        "outtmpl": str(output_dir / "%(title)s.%(ext)s"),

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    print(f"\nDownloading:\n{url}")
    print(f"Output directory: {output_dir}\n")

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])

    print("\nDownload complete!")


def main():
    # URL supplied through CLI
    if len(sys.argv) > 1:
        url = sys.argv[1]

    # Otherwise prompt for URL
    else:
        url = input("Paste YouTube URL: ").strip()

    if not url:
        print("No URL provided.")
        sys.exit(1)

    download_audio(url)


if __name__ == "__main__":
    main()
