from wordcloud import WordCloud
import matplotlib.pyplot as plt

with open('/home/david/Projects/Tello_mr_ros_ws/src/tello_mixed_reality_handcontrol/wordcloud/feedback.txt', 'r', encoding='utf-8') as f:
    text = f.read()

wordcloud = WordCloud(width=1000, height=500, background_color='white').generate(text)

plt.figure(figsize=(10, 5))
plt.imshow(wordcloud, interpolation='bilinear')
plt.axis('off')
plt.show()
