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
import threading
import uuid

# Instância global da API (v1.2+ requer instanciação)
_yt_api = YouTubeTranscriptApi()

app = Flask(__name__)

# Resolução mínima oferecida nos downloads de vídeo + áudio
MIN_VIDEO_HEIGHT = 720

# Progresso dos downloads em andamento, consultado pelo frontend via /download_progress
_download_jobs = {}
_jobs_lock = threading.Lock()

# Configuração OpenAI
# Chave lida apenas da variável de ambiente (.env / docker-compose)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY nao definida. Configure-a no arquivo .env ou nas variaveis de ambiente.")
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
        # youtube_transcript_api v1.2+: instância com api.list() e api.fetch()
        transcript_list = _yt_api.list(vid)

        transcript = None
        try:
            # Prefere português
            transcript = transcript_list.find_transcript(['pt', 'pt-BR'])
        except Exception:
            # Fallback: qualquer idioma disponível
            transcript = next(iter(transcript_list))

        seq = transcript.fetch()
        # v1.2 retorna FetchedTranscriptSnippet com atributo .text (não dict)
        texto = " ".join(
            item.text if hasattr(item, 'text') else item.get('text', '')
            for item in seq
        )
        return jsonify({'transcription': texto})

    except (TranscriptsDisabled, NoTranscriptFound) as e:
        print(f"API Error: {e}. Trying yt-dlp fallback.")
        try:
            texto = transcribe_with_ytdlp(url)
            return jsonify({'transcription': texto})
        except Exception as e2:
            return jsonify({'error': f"Could not transcribe video: {str(e2)}"}), 500
    except Exception as e:
        print(f"Transcribe error: {type(e).__name__}: {e}")
        traceback.print_exc()
        # Tenta yt-dlp como fallback para erros inesperados também
        try:
            texto = transcribe_with_ytdlp(url)
            return jsonify({'transcription': texto})
        except Exception as e2:
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
        ydl_opts = {
            'quiet': True,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get('formats', [])
        formats_info = []

        video_heights = [1080, 720, 480, 360]

        # Melhor áudio disponível, usado para muxar com os vídeos sem trilha sonora
        audio_only = [
            f for f in formats
            if f.get('acodec') not in (None, 'none')
            and f.get('vcodec') in (None, 'none')
            and f.get('url')
        ]
        best_audio_size = 0
        if audio_only:
            best_audio = max(audio_only, key=lambda f: f.get('abr') or 0)
            best_audio_size = best_audio.get('filesize') or best_audio.get('filesize_approx') or 0

        # 1) Vídeo + Áudio a partir de 720p. O YouTube só entrega progressive até 360p,
        # então as resoluções altas são vídeo puro e o áudio é combinado pelo ffmpeg.
        seen_va = set()
        va_candidates = [
            f for f in formats
            if f.get('vcodec') not in (None, 'none') and f.get('height') and f.get('url')
        ]
        # Ordena por resolução/fps e privilegia mp4 (h264) por compatibilidade
        va_candidates.sort(
            key=lambda f: (f.get('height'), f.get('fps') or 0, f.get('ext') == 'mp4', f.get('tbr') or 0),
            reverse=True
        )
        for f in va_candidates:
            h = f.get('height')
            if h < MIN_VIDEO_HEIGHT:
                continue
            key = (h, f.get('fps'))
            if key in seen_va:
                continue
            seen_va.add(key)
            size = f.get('filesize', 0) or f.get('filesize_approx', 0)
            if f.get('acodec') not in (None, 'none'):
                format_id = f.get('format_id')
                ext = f.get('ext')
            else:
                fid = f.get('format_id')
                format_id = f"{fid}+bestaudio[ext=m4a]/{fid}+bestaudio"
                ext = 'mp4'
                size = (size + best_audio_size) if size else 0
            formats_info.append({
                'type': 'video_audio',
                'format_id': format_id,
                'resolution': f"{h}p",
                'fps': f.get('fps', ''),
                'ext': ext,
                'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
            })

        # Se o vídeo não tiver nenhuma faixa em 720p ou mais, oferece o que existir
        if not formats_info:
            for f in va_candidates:
                if f.get('acodec') in (None, 'none'):
                    continue
                size = f.get('filesize', 0) or f.get('filesize_approx', 0)
                formats_info.append({
                    'type': 'video_audio',
                    'format_id': f.get('format_id'),
                    'resolution': f"{f.get('height')}p",
                    'fps': f.get('fps', ''),
                    'ext': f.get('ext'),
                    'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
                })

        # 2) Só Vídeo (sem áudio) — alta qualidade, precisa combinar com áudio
        seen_video = set()
        for f in formats:
            h = f.get('height')
            has_video = f.get('vcodec') not in (None, 'none')
            has_audio = f.get('acodec') not in (None, 'none')
            if has_video and not has_audio and h in video_heights and f.get('url'):
                key = (h, f.get('ext'))
                if key in seen_video:
                    continue
                seen_video.add(key)
                size = f.get('filesize', 0) or f.get('filesize_approx', 0)
                formats_info.append({
                    'type': 'video',
                    'format_id': f.get('format_id'),
                    'resolution': f"{h}p",
                    'fps': f.get('fps', ''),
                    'ext': f.get('ext'),
                    'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
                })

        # 3) Só Áudio
        seen_audio = set()
        for f in formats:
            if f.get('acodec') not in (None, 'none') and f.get('vcodec') in (None, 'none') and f.get('url'):
                key = (f.get('ext'), f.get('abr'))
                if key in seen_audio:
                    continue
                seen_audio.add(key)
                size = f.get('filesize', 0) or f.get('filesize_approx', 0)
                formats_info.append({
                    'type': 'audio',
                    'format_id': f.get('format_id'),
                    'bitrate': f"{f.get('abr', '')}kbps",
                    'ext': f.get('ext'),
                    'size_mb': f"{size / (1024 * 1024):.2f} MB" if size else "Unknown"
                })

        if not formats_info:
            return jsonify({'error': 'Nenhum formato disponível para este vídeo. O YouTube pode estar bloqueando o acesso.'}), 500

        return jsonify({'formats': formats_info})
    except Exception as e:
        print(f"list_formats error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _update_job(job_id, **fields):
    with _jobs_lock:
        job = _download_jobs.get(job_id)
        if job:
            job.update(fields)


def _format_speed(speed):
    if not speed:
        return ''
    return f"{speed / (1024 * 1024):.1f} MB/s"


def _format_eta(eta):
    if not eta:
        return ''
    return f"{int(eta) // 60:02d}:{int(eta) % 60:02d}"


def _run_download(job_id, url, format_id, convert_to_mp3):
    def progress_hook(d):
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            info = d.get('info_dict') or {}
            is_audio = info.get('vcodec') in (None, 'none')
            _update_job(
                job_id,
                status='downloading',
                percent=round(downloaded / total * 100, 1) if total else 0,
                stage='Baixando áudio' if is_audio else 'Baixando vídeo',
                speed=_format_speed(d.get('speed')),
                eta=_format_eta(d.get('eta')),
            )
        elif d.get('status') == 'finished':
            _update_job(job_id, percent=100, speed='', eta='', stage='Processando')

    def postprocessor_hook(d):
        if d.get('status') != 'started':
            return
        name = str(d.get('postprocessor') or '')
        if name == 'Merger':
            stage = 'Juntando vídeo e áudio'
        elif 'ExtractAudio' in name:
            stage = 'Convertendo para MP3'
        else:
            return
        _update_job(job_id, status='processing', percent=100, stage=stage, speed='', eta='')

    try:
        download_dir = os.path.join(os.getcwd(), 'downloads')
        os.makedirs(download_dir, exist_ok=True)

        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'progress_hooks': [progress_hook],
            'postprocessor_hooks': [postprocessor_hook],
        }

        if '+' in format_id and not convert_to_mp3:
            ydl_opts['merge_output_format'] = 'mp4'

        if convert_to_mp3:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            # Após mux/pós-processamento o caminho real vem em requested_downloads
            requested = (info.get('requested_downloads') or [{}])[0]
            filename = requested.get('filepath') or ydl.prepare_filename(info)

            # Se foi convertido para MP3, ajusta a extensão
            if convert_to_mp3:
                filename = os.path.splitext(filename)[0] + '.mp3'

        if not os.path.exists(filename):
            # Fallback: busca o arquivo mais recente na pasta downloads
            files = sorted(
                [os.path.join(download_dir, f) for f in os.listdir(download_dir)],
                key=os.path.getmtime,
                reverse=True
            )
            if not files:
                _update_job(job_id, status='error', error='Arquivo baixado mas não encontrado para envio')
                return
            filename = files[0]

        _update_job(
            job_id,
            status='done',
            percent=100,
            stage='Concluído',
            speed='',
            eta='',
            filename=os.path.basename(filename),
            filepath=filename,
        )
    except Exception as e:
        print(f"download_file error: {e}")
        traceback.print_exc()
        _update_job(job_id, status='error', error=str(e))


@app.route('/download_file', methods=['POST'])
def download_file():
    url = request.form.get('url')
    format_id = request.form.get('format_id')
    convert_to_mp3 = request.form.get('convert_to_mp3', 'false').lower() == 'true'
    
    if not url or not format_id:
        return jsonify({'error': 'Please provide URL and format ID'}), 400

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _download_jobs[job_id] = {
            'status': 'starting',
            'percent': 0,
            'stage': 'Preparando',
            'speed': '',
            'eta': '',
            'filename': None,
            'error': None,
        }

    thread = threading.Thread(
        target=_run_download,
        args=(job_id, url, format_id, convert_to_mp3),
        daemon=True,
    )
    thread.start()

    return jsonify({'job_id': job_id})


@app.route('/download_progress/<job_id>', methods=['GET'])
def download_progress(job_id):
    with _jobs_lock:
        job = _download_jobs.get(job_id)
        if not job:
            return jsonify({'error': 'Job não encontrado'}), 404
        return jsonify({k: v for k, v in job.items() if k != 'filepath'})


@app.route('/download_result/<job_id>', methods=['GET'])
def download_result(job_id):
    with _jobs_lock:
        job = _download_jobs.get(job_id)
        if not job:
            return jsonify({'error': 'Job não encontrado'}), 404
        if job['status'] != 'done':
            return jsonify({'error': 'Download ainda não terminou'}), 409
        filepath = job['filepath']

    if not os.path.exists(filepath):
        return jsonify({'error': 'Arquivo baixado mas não encontrado para envio'}), 500

    return send_from_directory(
        os.path.dirname(filepath),
        os.path.basename(filepath),
        as_attachment=True
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=False)
