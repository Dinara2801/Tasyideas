from io import BytesIO

from django.db.models import Count, F, Prefetch, Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from djoser.views import UserViewSet as DjoserUserViewSet
from rest_framework import filters, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.response import Response

from .filters import RecipeFilter
from .permissions import IsAuthorOrReadOnly
from .serializers import (
    FavoriteSerializer,
    FollowCreateSerializer,
    FollowReadSerializer,
    IngredientSerializer,
    RecipeWriteSerializer,
    ShoppingCartSerializer,
    ShortRecipeLinkSerializer,
    TagSerializer,
    UserAvatarUploadSerializer,
    UserSerializer
)
from core.shopping_cart import generate_shopping_list_text
from recipes.models import (
    Favorite,
    Ingredient,
    IngredientInRecipe,
    Recipe,
    ShoppingCart,
    Tag
)
from users.models import Follow, User


class UserViewSet(DjoserUserViewSet):
    queryset = User.objects.all()
    pagination_class = LimitOffsetPagination

    @action(
        detail=False,
        methods=('get',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def me(self, request):
        serializer = UserSerializer(
            request.user,
            context={'request': request}
        )
        return Response(serializer.data)

    @action(
        detail=False,
        methods=('put',),
        permission_classes=(permissions.IsAuthenticated,),
        url_path='me/avatar'
    )
    def avatar(self, request):
        """Метод для добавления аватара текущего пользователя."""
        if 'avatar' not in request.data:
            return Response(
                {'avatar': 'Это поле обязательно для загрузки аватара.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = UserAvatarUploadSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @avatar.mapping.delete
    def delete_avatar(self, request):
        """Метод для удаления аватара текущего пользователя."""
        user = request.user
        user.avatar.delete(save=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=False,
        methods=('get',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def subscriptions(self, request):
        """Метод для просмотра всех подписок пользователя."""
        page = self.paginate_queryset(User.objects.filter(
            subscriptions_on_author__user=request.user
        ).annotate(recipes_count=Count('recipes')).order_by('username'))
        serializer = FollowReadSerializer(
            page, many=True, context={'request': request}
        )
        return self.get_paginated_response(serializer.data)

    @action(
        detail=True,
        methods=('post',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def subscribe(self, request, id=None):
        """Метод для создания подписки на автора."""
        author = get_object_or_404(User, id=id)
        serializer = FollowCreateSerializer(
            data={'author': author.id, 'user': request.user.id},
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED
        )

    @subscribe.mapping.delete
    def unsubscribe(self, request, id=None):
        """Метод для удаления подписки на автора."""
        author = get_object_or_404(User, id=id)
        deleted, _ = Follow.objects.filter(
            user=request.user,
            author=author
        ).delete()
        return (
            Response(status=status.HTTP_204_NO_CONTENT)
            if deleted else
            Response(
                {'errors': 'Вы не подписаны на этого пользователя.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        )


class TagViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet для чтения информации о тегах."""

    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    pagination_class = None


class IngredientViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet для чтения информации об ингредиентах."""

    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    filter_backends = (filters.SearchFilter,)
    search_fields = ('^name',)
    pagination_class = None


class RecipeViewSet(viewsets.ModelViewSet):
    """ViewSet для создания, редактирования и чтения рецептов."""

    queryset = Recipe.objects.all().select_related(
        'author'
    ).prefetch_related(
        'tags',
        Prefetch(
            'ingredientinrecipe_set',
            queryset=IngredientInRecipe.objects.select_related('ingredient')
        )
    )
    serializer_class = RecipeWriteSerializer
    filter_backends = (DjangoFilterBackend,)
    filterset_class = RecipeFilter
    permission_classes = (IsAuthorOrReadOnly,)

    def _create_relation(self, serializer_class, pk):
        recipe = get_object_or_404(Recipe, id=pk)
        data = {
            'user': self.request.user.id,
            'recipe': recipe.id
        }
        serializer = serializer_class(
            data=data, context={'request': self.request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _delete_relation(self, model, pk):
        recipe = get_object_or_404(Recipe, id=pk)
        deleted, _ = model.objects.filter(
            user=self.request.user,
            recipe__id=recipe.id
        ).delete()
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            status=status.HTTP_400_BAD_REQUEST
        )

    @action(
        detail=True,
        methods=('post',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def favorite(self, request, pk=None):
        """Метод для добавления рецепта в избранное."""
        return self._create_relation(FavoriteSerializer, pk)

    @favorite.mapping.delete
    def unfavorite(self, request, pk=None):
        """Метод для удаления рецепта из избранного."""
        return self._delete_relation(Favorite, pk)

    @action(
        detail=True,
        methods=('post',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def shopping_cart(self, request, pk=None):
        """Метод для добавления рецепта в список покупок."""
        return self._create_relation(ShoppingCartSerializer, pk)

    @shopping_cart.mapping.delete
    def remove_shopping_cart(self, request, pk=None):
        """Метод для удаления рецепта из списка покупок."""
        return self._delete_relation(ShoppingCart, pk)

    @action(detail=True, methods=('get',), url_path='get-link')
    def short_link(self, request, pk=None):
        """Метод для получения короткой ссылки на рецепт."""
        return Response(
            ShortRecipeLinkSerializer(
                self.get_object(), context={'request': request}
            ).data,
            status=status.HTTP_200_OK
        )

    @action(
        detail=False,
        methods=('get',),
        permission_classes=(permissions.IsAuthenticated,)
    )
    def download_shopping_cart(self, request):
        """Метод для скачивания списка покупок."""
        ingredients = IngredientInRecipe.objects.filter(
            recipe__in_shoppingcarts__user=request.user
        ).values(
            name=F('ingredient__name'),
            unit=F('ingredient__measurement_unit')
        ).annotate(total_amount=Sum('amount')).order_by('name')

        content = generate_shopping_list_text(ingredients)
        buffer = BytesIO()
        buffer.write(content.encode('utf-8'))
        buffer.seek(0)
        response = FileResponse(
            buffer,
            content_type='text/plain; charset=utf-8'
        )
        response[
            'Content-Disposition'
        ] = 'attachment; filename="shopping_list.txt"'
        return response
