#!/usr/bin/env python3

# ライブラリの読み込み
import cv2
import boto3
import threading
import json
import datetime
import os
import wave
import glob
import subprocess
from flask import Flask, render_template, send_from_directory, request
from flask_socketio import SocketIO


class DemoApp:
    def __init__(self):
        # 動体検出
        self.previous_frame = None  # 前のフレームを保持する変数

        # Amazon Web Serviceを利用するための準備
        self.rekognition = boto3.client(service_name="rekognition")  # 画像認識サービス
        self.translate = boto3.client(service_name="translate")  # 翻訳サービス
        self.polly = boto3.client(service_name="polly")  # 音声合成サービス

        # アプリの設定
        self.data_dir = "./datas"
        self.collection_max = 1000

        # 状態を表す変数
        self.is_initialized = False
        self.is_detection_paused = False

        # 表情認識の単語
        # キー: {キーを翻訳したもの, 発話させるワード}
        self.emotion = {
            "HAPPY": {"translate": "幸せ", "speech": "嬉しそうだね！"},
            "SAD": {"translate": "悲しい", "speech": "悲しそうだね..."},
            "ANGRY": {"translate": "怒り", "speech": "怒ってるの？"},
            "CONFUSED": {"translate": "困惑", "speech": "困惑してる？"},
            "DISGUSTED": {"translate": "うんざり", "speech": "うんざりしたの？"},
            "SURPRISED": {"translate": "驚き", "speech": "驚いているね！"},
            "CALM": {"translate": "穏やか", "speech": "落ち着いているね～"},
            "FEAR": {"translate": "不安", "speech": "不安そうだね..."},
            "UNKNOWN": {"translate": "不明", "speech": "よくわからない表情だね..."},
        }

        # データを置く場所を作成
        if not os.path.isdir(self.data_dir):
            os.makedirs(self.data_dir)

    def motion_detect(self, image, max_score=80000):
        """動体検出の関数"""

        mono = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)  # グレースケール変換

        # 前のフレームがないときは、現在のフレームを入れる
        if self.previous_frame is None:
            self.previous_frame = mono.copy().astype("float")  # フレームをコピー
            return False  # 前と現在のフレームが同じだと判定できないので、Falseを返す

        # 動体検出の処理
        cv2.accumulateWeighted(mono, self.previous_frame, 0.6)  # 加重平均の計算
        mask = cv2.absdiff(mono, cv2.convertScaleAbs(self.previous_frame))  # 差分画像の作成
        thresh = cv2.threshold(mask, 3, 255, cv2.THRESH_BINARY)[1]  # 差分画像を2値化
        score = cv2.countNonZero(thresh)  # 画像中の黒以外の要素を積算してスコアを算出

        # 指定したスコアを超えたら動体検出したとみなす
        if score > max_score:
            return True
        return False

    def pause_detection(self):
        """動体検出を一時停止する関数"""

        self.is_detection_paused = True
        threading.Timer(3, self.resume_detection).start()  # 指定した秒数後に関数を呼び出すスレッドを用意して実行

    def resume_detection(self):
        """動体検出を再開する関数"""

        self.previous_frame = None  # 検出に使ったデータを空にする
        self.is_detection_paused = False

    def listup(self):
        """保存されている画像一覧を取得する関数"""

        return sorted(glob.glob("./datas/*.JPG"), key=lambda f: os.stat(f).st_mtime, reverse=True)

    def get_records(self):
        """保存された画像とメタ情報を取得する関数"""

        records = []
        for f in self.listup():
            records.append({
                "name": os.path.basename(f),
                "date": datetime.datetime.fromtimestamp(os.path.getctime(f)).strftime("%Y年%m月%d日 %H時%M分%S秒"),
                "meta": json.load(open(os.path.splitext(f)[0] + ".JSON", 'r'))
            })
        return records

    def encode_image(self, image):
        """JPEG形式のデータに変換する関数"""

        return cv2.imencode(".JPEG", image)[1].tobytes()

    def detect_labels(self, encode_image):
        """画像からラベル情報を取得する関数"""

        response_data = self.rekognition.detect_labels(Image={"Bytes": encode_image})
        return response_data["Labels"]

    def detect_faces(self, encode_image):
        """画像から顔検出する関数"""

        response_data = self.rekognition.detect_faces(Image={"Bytes": encode_image}, Attributes=["ALL"])
        return response_data["FaceDetails"]

    def transrate_text(self, text):
        """テキストを翻訳する関数"""

        response_data = self.translate.translate_text(Text=text, SourceLanguageCode="en", TargetLanguageCode="ja")
        return response_data["TranslatedText"]

    def synthesize_speech(self, text):
        """テキストから音声合成する関数"""

        return self.polly.synthesize_speech(Text=text, OutputFormat="pcm", VoiceId="Takumi")["AudioStream"]

    def synthesize_speech_wave(self, text, name, dir):
        """テキストから音声合成 + WAVファイルを生成する関数"""

        speech_data = self.synthesize_speech(text)
        wave_data = wave.open("{}/{}".format(dir, name), "wb")
        wave_data.setnchannels(1)
        wave_data.setsampwidth(2)
        wave_data.setframerate(16000)
        wave_data.writeframes(speech_data.read())
        wave_data.close()

    def total_data_size(self):
        """保存されているデータの容量を取得する関数"""

        total_data_size = int(subprocess.run("du -b datas", shell=True, encoding='utf-8', stdout=subprocess.PIPE).stdout.split("\t")[0])
        return "{:.1f}MB".format(total_data_size * 0.001 * 0.001)

    def process(self, image):
        """メインの処理を記述した関数"""

        if self.motion_detect(image=image):
            timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9), "JST"))

            encoded_image = self.encode_image(image=image)  # 画像をエンコード

            # Amazon Rekognitionで画像からラベル情報を取得する
            detect_labels_response = self.detect_labels(encode_image=encoded_image)

            # detect_labels_responseから各要素dのName属性の値を抽出してリストに追加
            labels = [d["Name"] for d in detect_labels_response]
            text = ""
            # Personが含まれる場合はさらに顔情報を取得
            if "Person" in labels:
                # Amazon Rekognitionで画像から顔や表情を取得する
                detect_faces_response = self.detect_faces(encode_image=encoded_image)

                # 結果が空でない場合は処理を継続
                if len(detect_faces_response) > 0:
                    face = detect_faces_response[0]  # 先頭のデータを取得
                    # バウンディングボックスを描画
                    x = int(face["BoundingBox"]["Left"] * image.shape[1])
                    y = int(face["BoundingBox"]["Top"] * image.shape[0])
                    w = int(face["BoundingBox"]["Width"] * image.shape[1])
                    h = int(face["BoundingBox"]["Height"] * image.shape[0])
                    image = cv2.rectangle(image, (x, y), (x + w, y + h), (255, 255, 255), 2)

                    emotion_type = face["Emotions"][0]["Type"]  # 表情を取り出す
                    emotion_type_translated = self.emotion[emotion_type]["translate"]  # 表情の日本語訳を取り出す

                    text = "{}".format(self.emotion[emotion_type]["speech"])  # 表情について発話させる文章を取り出す
                else:
                    text = "誰かいるね！"
                    emotion_type_translated = "無し"
            if "Cat" in labels:
                text = "猫がいるよ！！"
                emotion_type_translated = "無し"
            if "Dog" in labels:
                text = "犬がいるよ！！"
                emotion_type_translated = "無し"

            # 上記のいずれかの条件にも該当しなかった場合
            if text == "":
                text = "何か動いたよ！"
                emotion_type_translated = "無し"

            ####################################################################
            # ファイル名を作成
            base_name = timestamp.strftime("%Y%m%d_%H%M%S")

            text_labels = "\n".join(labels)  # ラベル情報を文字列化
            transrate_labels = self.transrate_text(text_labels).split("\n")[:-1]  # ラベル情報の文字列を翻訳して配列として返す

            # 読み上げる文章の音声ファイルを音声合成で作成
            audio_name = "{}.wav".format(base_name)
            self.synthesize_speech_wave(text, audio_name, self.data_dir)

            # 画像の保存
            image_name = "{}.JPG".format(base_name)
            cv2.imwrite("{}/{}".format(self.data_dir, image_name), img=image)

            # メタ情報の保存
            meta_name = "{}.JSON".format(base_name)
            meta = {}
            meta["Labels"] = transrate_labels
            meta["EmotionType"] = emotion_type_translated
            json.dump(meta, open("{}/{}".format(self.data_dir, meta_name), mode="w"), ensure_ascii=False, indent=4, sort_keys=True)

            # 指定枚数以上は古いものから削除
            for i, f in enumerate(self.listup()):
                if i > self.collection_max:
                    [os.remove(t) for t in glob.glob("{}*".format(os.path.splitext(f)[0]))]

            self.pause_detection()  # 動体検出を一定時間止める

            # クライアントに送るデータを作成して返す
            return {
                "text": text,
                "image": image_name,
                "audio": audio_name,
                "date": timestamp.strftime("%Y年%m月%d日 %H時%M分%S秒"),
                "meta": meta,
                "tsize": self.total_data_size()
            }
        else:
            return None


app = Flask(__name__)  # フラスクアプリを作成
app.jinja_options.update({"variable_start_string": "[[", "variable_end_string": "]]", })  # テンプレートエンジンの設定を変更
socketio = SocketIO(app)  # WebSocket通信のインスタンスを作成
demo = DemoApp()  # デモアプリを作成


@app.route("/")
def main():
    """トップページにアクセスしたときに実行される関数"""
    return render_template("index.html")


@app.route("/datas/<path:name>")
def datas(name):
    """datas/〇〇.xxという形式のURLでファイルをダウンロードできるようにする設定"""
    return send_from_directory("./datas", name)


@socketio.on("connect")
def connect():
    """WebSocketで接続がされたときに実行される関数"""
    init_data = json.dumps({"records": demo.get_records(), "tsize": demo.total_data_size()})
    socketio.emit("init", init_data, to=request.sid)
    if not demo.is_initialized:
        demo.is_initialized = True
        socketio.start_background_task(target=background_task)


def background_task():
    """
    Webサーバと並行して実行される処理
    ここで動体検出やAWSの処理などを実行します
    """
    # カメラの設定
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    while True:
        success, image = cap.read()
        if not success or demo.is_detection_paused:
            continue
        message = demo.process(image=image)
        if message is not None:
            socketio.emit("update", json.dumps(message))
        cv2.waitKey(1)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=8080, debug=True)
