//--------------------------------------------------------------------------------

// Piniaを使って、状態を管理する
const stateStore = Pinia.defineStore("status", {
  state: () => {
    return {
      playSound: false, // 音声再生を許可しているか
      currentIcon: "md-volume-off", // 音声再生の許可ボタンのアイコン名
      cameraPhoto: "./static/assets/no_image.png", // 撮影された写真のファイル名（初回はNo Image画像を設定）
      speechBubbleText: "No Received", // 吹き出し内のテキスト
      timeStampText: "No Received", // 写真右下に表示している撮影日のテキスト
      recordPhotos: [], // いままでに記録された写真情報が収納されている配列
      previewPhoto: "", // 画面下のリストをクリックしたときに表示されるプレビュー写真
      previewVisible: false, // プレビュー写真を表示するかどうか
      isPortrait: ons.orientation.isPortrait(), // 画面の向き
      openSide: false, // サイドパネルを表示するかどうか
      totalDataSize: 0, // 合計の画像データ量
    };
  },
  actions: {},
});

//--------------------------------------------------------------------------------

// アプリ本体を作成
const app = Vue.createApp({
  template: "#main",
  setup() {
    // iOSのデザインに統一する
    ons.disableAutoStyling();
    // WebSocket通信の準備
    const ws = io.connect(location.protocol + "//" + location.hostname + ":" + location.port); // WebSocketの通信準備
    // 状態管理の準備
    const status = stateStore();
    return { status, ws };
  },
  methods: {
    // 音声再生許可のボタンを押したときの関数
    updateSoundMode() {
      this.status.playSound = !this.status.playSound;
      if (this.status.playSound) {
        // ブラウザの仕様上、なんらかの音声を再生しないといけないので、無音ファイルを再生
        new Howl({ src: ["./static/assets/silence.wav"], volume: 0 });
        this.status.currentIcon = "md-volume-up";
      } else {
        this.status.currentIcon = "md-volume-off";
      }
    },
    // リストで画像をクリックしたときにプレビュー画像を表示するための関数
    showPreview(image) {
      this.status.previewPhoto = "./datas/" + image;
      this.status.previewVisible = true;
    },
    // プレビュー画像を閉じるときの関数
    closePreview() {
      this.status.previewPhoto = "";
      this.status.previewVisible = false;
    },
    // サイドメニューを表示するための関数
    showMenu() {
      this.status.openSide = true;
    },
    // サイドメニューを閉じるための関数
    closeMenuEvent(event) {
      this.status.openSide = false;
    },
  },
  mounted() {
    // サーバから"Init"のデータを受信したとき
    this.ws.on("init", (data) => {
      // 受信データを取り出す
      data = JSON.parse(data);
      // データから写真情報を取り出して、配列に追加する。
      for (let i = 0; i < data.records.length; i++) {
        this.status.recordPhotos.push({
          name: data.records[i].name,
          date: data.records[i].date,
          emotion: data.records[i].meta.EmotionType,
          labels: data.records[i].meta.Labels.slice(0, 3).join(", "),
        });
      }
      // 合計の画像データ量を更新
      this.status.totalDataSize = data.tsize;
    });

    // サーバから"Update"のデータを受信したとき
    this.ws.on("update", (data) => {
      data = JSON.parse(data);
      this.status.cameraPhoto = "./datas/" + data.image;
      this.status.speechBubbleText = data.text;
      this.status.timeStampText = data.date;
      this.status.totalDataSize = data.tsize;

      // 音声を再生
      if (this.status.playSound && this.status.isPortrait) {
        new Howl({
          src: ["./datas/" + data.audio],
          preload: true, // 事前ロード
          volume: 1.0, // 音量(0.0〜1.0の範囲で指定)
          loop: false, // ループ再生するか
          autoplay: true, // 自動再生するか
        });
      }

      // 画像リストを更新
      this.status.recordPhotos.unshift({
        name: data.image,
        date: data.date,
        emotion: data.meta.EmotionType,
        labels: data.meta.Labels.slice(0, 3).join(", "),
      });
    });

    // 画面の向きが変化したとき
    ons.orientation.on("change", (event) => {
      this.status.isPortrait = event.isPortrait;
    });
  },
});

// アプリをWebページに反映する
app.use(window["vue-lazyload"].default, { loading: "./static/assets/no_image.png" });
app.use(Pinia.createPinia());
app.use(VueOnsen);
app.mount("#app");
