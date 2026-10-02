import sys
import yt_dlp


def download_audio(url):
    options = {
        "format": "bestaudio/best",
        "outtmpl": "%(title)s.%(ext)s",

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    print(f"\nDownloading:\n{url}\n")

    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])

    print("\nDownload complete!")


def main():
    # If URL was supplied from the command line
    if len(sys.argv) > 1:
        url = sys.argv[1]

    # Otherwise ask for it
    else:
        url = input("Paste YouTube URL: ").strip()

    if not url:
        print("No URL provided.")
        sys.exit(1)

    download_audio(url)


if __name__ == "__main__":
    main()
