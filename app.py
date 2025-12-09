from flask import Flask, request, jsonify, render_template, send_from_directory
import os
import traceback
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import yt_dlp
import requests
import re
import tempfile
import openai
import math

app = Flask(__name__)

# Configuração OpenAI
# Tenta pegar da variável de ambiente (Seguro para VPS/GitHub)
# Se não houver, usa a chave hardcoded (apenas para desenvolvimento local)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua_api_key")
openai.api_key = OPENAI_API_KEY

# Helper function to extract video ID
def extract_video_id(url):
    match = re.search(r"(?:v=|\.be/)([A-Za-z0-9_-]{11})", url)
    return match.group(1) if match else None

def extract_subtitle_text(subtitle_formats):
    """Extrai texto das legendas baixadas via yt-dlp"""
    for fmt in subtitle_formats:
        if fmt.get('ext') in ['json3', 'srv3', 'vtt']:
            url = fmt.get('url')
            if url:
                try:
                    response = requests.get(url)
                    content = response.text
                    
                    if 'json' in fmt.get('ext', ''):
                        import json
                        data = json.loads(content)
                        events = data.get('events', [])
                        texts = []
                        for event in events:
                            segs = event.get('segs', [])
                            for seg in segs:
                                if 'utf8' in seg:
                                    texts.append(seg['utf8'])
                        return ' '.join(texts)
                    else:
                        # VTT - remove tags e timestamps
                        lines = content.split('\n')
                        texts = []
                        for line in lines:
                            line = line.strip()
                            if line and not line.startswith('WEBVTT') and '-->' not in line and not line.isdigit():
                                line = re.sub(r'<[^>]+>', '', line)
                                if line:
                                    texts.append(line)
                        return ' '.join(texts)
                except Exception as e:
                    print(f"Error processing format {fmt.get('ext')}: {e}")
                    continue
    return None

def transcribe_with_ytdlp(url):
    """Fallback transcript with yt-dlp"""
    ydl_opts = {
        'skip_download': True,
        'writesubtitles': True,
        'writeautomaticsub': True,
        'subtitleslangs': ['pt', 'pt-BR', 'en'],
        'quiet': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        subtitles = info.get('subtitles', {})
        automatic_captions = info.get('automatic_captions', {})
        
        subtitle_text = None
        for lang in ['pt-BR', 'pt', 'en']:
            if lang in subtitles:
                subtitle_text = extract_subtitle_text(subtitles[lang])
                break
            elif lang in automatic_captions:
                subtitle_text = extract_subtitle_text(automatic_captions[lang])
                break
        
        if subtitle_text:
            return subtitle_text
        else:
            raise Exception("Nenhuma legenda encontrada via yt-dlp")

# --- Lógica do Parafraseador ---
def dividir_em_chunks(texto, max_chars=3000):
    return [texto[i:i+max_chars] for i in range(0, len(texto), max_chars)]

@app.route('/paraphrase', methods=['POST'])
def paraphrase():
    data = request.json
    texto = data.get('text', '')
    idioma = data.get('language', 'Português (Brasil)')
    modelo = data.get('model', 'gpt-3.5-turbo')
    
    if not texto:
        return jsonify({'error': 'Texto vazio.'}), 400

    partes = dividir_em_chunks(texto)
    resultado = ""
    
    try:
        for parte in partes:
            prompt = f"Reescreva o texto a seguir em {idioma}, mantendo o sentido, mas usando outras palavras:\n\n{parte}"
            resposta = openai.chat.completions.create(
                model=modelo,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500,
                temperature=0.7,
            )
            resultado += resposta.choices[0].message.content.strip() + " "
            
        return jsonify({'result': resultado.strip()})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Lógica do Gerador STR ---
def segundos_para_str(segundos):
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = int(segundos % 60)
    return f"{h:02}:{m:02}:{s:02}"

@app.route('/generate_srt', methods=['POST'])
def generate_srt():
    data = request.json
    texto = data.get('text', '')
    
    if not texto:
        return jsonify({'error': 'Texto vazio.'}), 400
    
    # Normaliza o texto: remove quebras de linha e espaços extras
    texto = ' '.join(texto.split())
        
    max_chars = 360
    duracao_legenda = 30
    intervalo = 10
    legendas = []
    tempo_atual = 0
    idx = 0
    num_legenda = 1
    
    try:
        while idx < len(texto):
            bloco = texto[idx:idx+max_chars]
            if idx + max_chars < len(texto):
                # Procura o último ponto final dentro do limite
                corte = bloco.rfind('.')
                if corte != -1:
                    # Inclui o ponto final no bloco
                    bloco = bloco[:corte+1]
                    idx += corte + 1
                else:
                    # Se não houver ponto, procura espaço (fallback)
                    corte = bloco.rfind(' ')
                    if corte != -1:
                        bloco = bloco[:corte]
                        idx += corte + 1
                    else:
                        idx += max_chars
            else:
                idx += max_chars
                
            inicio = f"{segundos_para_str(tempo_atual)},000"
            fim = f"{segundos_para_str(tempo_atual + duracao_legenda)},000"
            legendas.append(f"{num_legenda}\n{inicio} --> {fim}\n{bloco}\n")
            
            tempo_atual += duracao_legenda + intervalo
            num_legenda += 1
            
        return jsonify({'result': '\n'.join(legendas)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/transcribe', methods=['POST'])
def transcribe():
    url = request.form.get('url')
    if not url:
         return jsonify({'error': 'URL not provided'}), 400
         
    vid = extract_video_id(url)
    if not vid:
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    try:
        # Try finding transcript via API
        if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            transcript_list = YouTubeTranscriptApi.list_transcripts(vid)
            
            try:
                # Prefer Portuguese
                transcript = transcript_list.find_transcript(['pt', 'pt-BR'])
            except:
                # Fallback to any available
                transcript = next(iter(transcript_list))
                
            seq = transcript.fetch()
            texto = " ".join([s['text'] for s in seq])
            return jsonify({'transcription': texto})
        else:
             # Legacy list method
             seq = YouTubeTranscriptApi.get_transcript(vid, languages=['pt-BR', 'pt'])
             texto = " ".join([s['text'] for s in seq])
             return jsonify({'transcription': texto})

    except (TranscriptsDisabled, NoTranscriptFound) as e:
        print(f"API Error: {e}. Trying yt-dlp fallback.")
        try:
            texto = transcribe_with_ytdlp(url)
            return jsonify({'transcription': texto})
        except Exception as e2:
             return jsonify({'error': f"Could not transcribe video: {str(e2)}"}), 500
    except Exception as e:
        error_msg = str(e)
        if "no element found" in error_msg.lower() or "xml" in error_msg.lower():
             print(f"XML Error ({e}). Trying yt-dlp fallback.")
             try:
                 texto = transcribe_with_ytdlp(url)
                 return jsonify({'transcription': texto})
             except Exception as e2:
                 return jsonify({'error': f"Could not transcribe video: {str(e2)}"}), 500
        else:
            return jsonify({'error': str(e)}), 500

@app.route('/thumbnail', methods=['POST'])
def thumbnail():
    url = request.form.get('url')
    vid = extract_video_id(url)
    if not vid:
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    thumbnail_url = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    return jsonify({'thumbnail_url': thumbnail_url})

@app.route('/download', methods=['POST'])
def list_formats():
    url = request.form.get('url')
    if not url:
        return jsonify({'error': 'Please provide a valid URL'}), 400

    try:
        ydl_opts = {'quiet': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        formats_info = []
        
        # Video formats (filter for typical resolutions)
        for f in formats:
            if f.get('vcodec') != 'none' and f.get('height') in [1080, 720]:
                size = f.get('filesize', 0) or f.get('filesize_approx', 0)
                formats_info.append({
                    'type': 'video',
                    'format_id': f.get('format_id'),
                    'resolution': f"{f.get('height')}p",
                    'fps': f.get('fps', ''),
                    'ext': f.get('ext'),
                    'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
                })
        
        # Audio formats
        for f in formats:
            if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                size = f.get('filesize', 0) or f.get('filesize_approx', 0)
                formats_info.append({
                    'type': 'audio',
                    'format_id': f.get('format_id'),
                    'bitrate': f"{f.get('abr', '')}kbps",
                    'ext': f.get('ext'),
                    'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
                })

        return jsonify({'formats': formats_info})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_file', methods=['POST'])
def download_file():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    convert_to_mp3 = request.form.get('convert_to_mp3', 'false').lower() == 'true'
    
    if not url or not format_id:
        return jsonify({'error': 'Please provide URL and format ID'}), 400

    try:
        # Create downloads directory if not exists
        download_dir = os.path.join(os.getcwd(), 'downloads')
        os.makedirs(download_dir, exist_ok=True)
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': f'{download_dir}/%(title)s.%(ext)s',
            'noplaylist': True
        }
        
        if convert_to_mp3:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'video')
            
            # Since outtmpl is set, we can try to guess the filename or re-find it.
            # A robust way is to use 'prepare_filename' but let's try searching by title match
            title_sanitized = info.get('title', '').replace('/', '_').replace('\\', '_')
            
            # Find the file
            target_file = None
            
            # Simpler approach: List dir and find matching title
            for file in os.listdir(download_dir):
                if title_sanitized in file:
                     # Basic check, might improve
                     target_file = file
                     # break # Don't break immediately, maybe find better match? No, first match is probably okay for now.
                     break
            
            if target_file:
                 return send_from_directory(download_dir, target_file, as_attachment=True)
            else:
                 return jsonify({'error': 'File downloaded but not found for sending'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=True)
