from nsfw_detector import predict
import os

def check_image(image):
    model = predict.load_model('nsfw_detector/nsfw_model.h5')

    results = predict.classify(model, image)
    # os.remove(image)
    hentai = results['data']['hentai']
    sexy = results['data']['sexy']
    porn = results['data']['porn']
    drawings = results['data']['drawings']
    neutral = results['data']['neutral']
    if neutral >= 25:
        results['data']['is_nsfw'] = False
    elif (sexy + porn + hentai) >= 70:
        results['data']['is_nsfw'] = True
    elif drawings >= 40:
        results['data']['is_nsfw'] = False
    else:
        results['data']['is_nsfw'] = False

    print(results)

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    path = "images"
    dir_list = os.listdir(path)

    for file in os.listdir(path):
        file = os.path.join(path, file)
        if file.endswith(".jpg"):
            check_image(file)



